"""
Pure Python RPC Solo Mining Client for Monacoin Core.
Connects directly to Monacoin Core via JSON-RPC, issues 'getblocktemplate',
constructs Coinbase transactions, Merkle roots, 76-byte block headers,
and submits mined blocks using 'submitblock'.
"""

import base64
import json
import struct
import urllib.request
import urllib.error
import hashlib
from typing import Optional, Tuple, Dict, Any

def sha256d(b: bytes) -> bytes:
    """Double SHA-256 hash."""
    return hashlib.sha256(hashlib.sha256(b).digest()).digest()

def encode_varint(n: int) -> bytes:
    """Encodes an integer into Bitcoin/Monacoin variable length integer (varint)."""
    if n < 0xfd:
        return bytes([n])
    elif n <= 0xffff:
        return b'\xfd' + struct.pack('<H', n)
    elif n <= 0xffffffff:
        return b'\xfe' + struct.pack('<I', n)
    else:
        return b'\xff' + struct.pack('<Q', n)

def encode_script_num_push(n: int) -> bytes:
    """
    Serialization of `CScript() << n` (Bitcoin/Monacoin Core), as required for the
    BIP34 block height at the start of the coinbase scriptSig.
    """
    if n == 0:
        return b'\x00'
    if 1 <= n <= 16:
        return bytes([0x50 + n])  # OP_1 .. OP_16
    data = bytearray()
    v = n
    while v:
        data.append(v & 0xff)
        v >>= 8
    if data[-1] & 0x80:
        data.append(0x00)  # keep the number positive
    return bytes([len(data)]) + bytes(data)


class SoloBlockTemplate:
    """
    Holds a retrieved block template and constructs block headers / full blocks.
    """
    def __init__(self, raw_gbt: dict, script_pubkey: bytes, wallet_address: str):
        self.raw = raw_gbt
        self.height: int = raw_gbt['height']
        self.version: int = raw_gbt['version']
        self.prev_hash_hex: str = raw_gbt['previousblockhash']
        self.bits_hex: str = raw_gbt['bits']
        self.curtime: int = raw_gbt['curtime']
        self.coinbase_value: int = raw_gbt['coinbasevalue']
        self.target_hex: str = raw_gbt['target']
        self.transactions: list = raw_gbt.get('transactions', [])
        self.default_witness_commitment: Optional[str] = raw_gbt.get('default_witness_commitment')
        
        self.script_pubkey = script_pubkey
        self.wallet_address = wallet_address
        
        # Two most significant 32-bit words of the 256-bit target (compared by the GPU kernel)
        self.target_int = int(self.target_hex, 16)
        self.target_high = (self.target_int >> 224) & 0xffffffff
        self.target_low = (self.target_int >> 192) & 0xffffffff

        # Build Coinbase TX and Merkle root
        self.cb_tx_bytes, self.cb_hash = self._build_coinbase_tx()
        self.merkle_root = self._build_merkle_root()
        self.header_76 = self._build_header_prefix()

    def _build_coinbase_tx(self) -> Tuple[bytes, bytes]:
        # BIP34: block height as the first item of the scriptSig
        scriptsig = encode_script_num_push(self.height) + b'/MonaMinerRTX-Solo/'

        tx = bytearray()
        tx += struct.pack('<i', 1) # version 1
        tx += encode_varint(1) # 1 input
        tx += b'\x00' * 32 # prevout hash (all zeros for coinbase)
        tx += struct.pack('<I', 0xffffffff) # prevout index
        tx += encode_varint(len(scriptsig))
        tx += scriptsig
        tx += struct.pack('<I', 0xffffffff) # sequence

        # Outputs
        has_witness = bool(self.default_witness_commitment)
        tx += encode_varint(2 if has_witness else 1)

        # Output 0: Mining reward to miner wallet
        tx += struct.pack('<Q', self.coinbase_value)
        tx += encode_varint(len(self.script_pubkey))
        tx += self.script_pubkey

        # Output 1 (Witness commitment if SegWit)
        if has_witness:
            w_script = bytes.fromhex(self.default_witness_commitment)
            tx += struct.pack('<Q', 0)
            tx += encode_varint(len(w_script))
            tx += w_script

        tx += struct.pack('<I', 0) # locktime
        cb_bytes = bytes(tx)

        # The txid (merkle leaf) is always the hash of the non-witness serialization.
        # In a block, a coinbase carrying a witness commitment must be serialized with
        # its witness (a single 32-byte reserved value of zeros).
        if has_witness:
            witness = encode_varint(1) + encode_varint(32) + b'\x00' * 32
            self.cb_tx_block_bytes = cb_bytes[:4] + b'\x00\x01' + cb_bytes[4:-4] + witness + cb_bytes[-4:]
        else:
            self.cb_tx_block_bytes = cb_bytes
        return cb_bytes, sha256d(cb_bytes)

    def _build_merkle_root(self) -> bytes:
        tx_hashes = [self.cb_hash]
        for t in self.transactions:
            # txid is in big-endian hex, convert to little-endian bytes
            tx_hashes.append(bytes.fromhex(t['txid'])[::-1])
            
        current = tx_hashes
        while len(current) > 1:
            if len(current) % 2 != 0:
                current.append(current[-1])
            nxt = []
            for i in range(0, len(current), 2):
                nxt.append(sha256d(current[i] + current[i+1]))
            current = nxt
        return current[0]

    def _build_header_prefix(self) -> bytes:
        """76-byte header prefix (excluding 4-byte nonce)."""
        hdr = bytearray()
        hdr += struct.pack('<i', self.version)
        hdr += bytes.fromhex(self.prev_hash_hex)[::-1]
        hdr += self.merkle_root
        hdr += struct.pack('<I', self.curtime)
        hdr += bytes.fromhex(self.bits_hex)[::-1]
        return bytes(hdr)

    def assemble_full_block(self, nonce: int) -> bytes:
        """Assembles the full serialized block with the winning nonce."""
        hdr = self.header_76 + struct.pack('<I', nonce)
        block = bytearray()
        block += hdr
        block += encode_varint(1 + len(self.transactions))
        block += self.cb_tx_block_bytes
        for t in self.transactions:
            block += bytes.fromhex(t['data'])
        return bytes(block)


class RpcSoloClient:
    """
    Manages communication with a local or remote Monacoin Core node.
    """
    def __init__(self, host: str = "127.0.0.1", port: int = 9402,
                 user: str = "monacoinrpc", password: str = "rpcpassword",
                 wallet_address: str = ""):
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.wallet_address = wallet_address
        self.cached_script_pubkey: Optional[bytes] = None
        self.last_block_template: Optional[SoloBlockTemplate] = None
        # True once the node itself said the reward address is invalid for its network (permanent error)
        self.address_invalid = False

    def call(self, method: str, params: list = None, timeout: float = 10.0) -> Dict[str, Any]:
        """Performs a raw JSON-RPC call."""
        if params is None:
            params = []
        payload = json.dumps({
            "jsonrpc": "1.0",
            "id": f"mona_solo_{method}",
            "method": method,
            "params": params
        }).encode("utf-8")
        
        auth_str = f"{self.user}:{self.password}"
        auth_b64 = base64.b64encode(auth_str.encode("utf-8")).decode("ascii")
        url = f"http://{self.host}:{self.port}/"
        
        req = urllib.request.Request(
            url,
            data=payload,
            headers={
                "Authorization": f"Basic {auth_b64}",
                "Content-Type": "application/json"
            }
        )
        
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = resp.read().decode("utf-8")
                return json.loads(data)
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="ignore")
            try:
                err_json = json.loads(err_body)
                return err_json
            except Exception:
                return {"error": {"code": e.code, "message": str(e)}}
        except Exception as e:
            return {"error": {"code": -1, "message": str(e)}}

    def test_connection(self) -> Tuple[bool, str, dict]:
        """
        Validates connection to Monacoin Core node and returns status summary.
        """
        res = self.call("getblockchaininfo")
        if "error" in res and res["error"]:
            return False, f"RPC接続エラー: {res['error'].get('message', res['error'])}", {}
        
        info = res.get("result", {})
        chain = info.get("chain", "unknown")
        blocks = info.get("blocks", 0)
        ibd = info.get("initialblockdownload", False)
        
        # Check network connections
        net_res = self.call("getnetworkinfo")
        conns = 0
        if "result" in net_res:
            conns = net_res["result"].get("connections", 0)
            
        summary = (
            f"接続成功 [チェーン: {chain.upper()}, ブロック高: #{blocks:,}, "
            f"接続ピア: {conns} 台, IBD中: {'はい' if ibd else 'いいえ'}]"
        )
        return True, summary, info

    def resolve_script_pubkey(self, address: str) -> Optional[bytes]:
        """
        Resolves the recipient address's scriptPubKey using Monacoin Core's validateaddress.
        Falls back to local P2PKH/P2SH decode if node call fails.
        """
        if not address:
            self.address_invalid = True
            return None

        res = self.call("validateaddress", [address])
        result = res.get("result")
        if isinstance(result, dict):
            if result.get("isvalid", False):
                spk_hex = result.get("scriptPubKey")
                if spk_hex:
                    self.address_invalid = False
                    return bytes.fromhex(spk_hex)
            else:
                self.address_invalid = True
        return None

    def get_block_template(self) -> Tuple[Optional[SoloBlockTemplate], Optional[str]]:
        """
        Fetches block template from Monacoin Core and constructs SoloBlockTemplate.
        """
        # Resolve scriptPubKey once or if address changes
        if not self.cached_script_pubkey:
            self.cached_script_pubkey = self.resolve_script_pubkey(self.wallet_address)
            if not self.cached_script_pubkey:
                if self.address_invalid:
                    return None, ("受取アドレスがこのノードのネットワークでは無効です。"
                                  "メインネットのノードには M... / mona1...、Regtest には rmona1... のアドレスを指定してください。")
                return None, "受取アドレスを検証できませんでした (ノードに接続できません)。"
                
        res = self.call("getblocktemplate", [{"rules": ["segwit"]}])
        if "error" in res and res["error"]:
            err_msg = res["error"].get("message", str(res["error"]))
            return None, f"getblocktemplate 取得エラー: {err_msg}"
            
        raw_gbt = res.get("result")
        if not raw_gbt:
            return None, "getblocktemplate レスポンスが空です。"
            
        template = SoloBlockTemplate(raw_gbt, self.cached_script_pubkey, self.wallet_address)
        self.last_block_template = template
        return template, None

    def submit_block(self, template: SoloBlockTemplate, nonce: int) -> Tuple[bool, str]:
        """
        Submits the mined block to Monacoin Core.
        Returns (is_accepted, message).
        """
        full_block = template.assemble_full_block(nonce)
        block_hex = full_block.hex()
        
        res = self.call("submitblock", [block_hex])
        if "error" in res and res["error"]:
            return False, f"拒絶 (RPCエラー): {res['error'].get('message')}"
            
        result = res.get("result")
        # Bitcoin/Monacoin Core submitblock returns None on success, or a string on failure (e.g. 'duplicate', 'high-hash')
        if result is None:
            return True, f"★ ブロック採掘・承認成功！ (ブロック高 #{template.height}, 報酬: {template.coinbase_value / 1e8:.2f} MONA)"
        else:
            return False, f"拒絶 (ブロック検証理由: {result})"
