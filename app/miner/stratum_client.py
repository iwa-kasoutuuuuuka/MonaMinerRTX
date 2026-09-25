"""
Pure Python Stratum Protocol (v1) client for Monacoin Lyra2REv2 mining.
Handles mining.subscribe, mining.authorize, mining.set_difficulty, mining.notify,
and block header calculation (Coinbase tx & Merkle Tree).
"""

import socket
import json
import time
import struct
import hashlib
import binascii
import threading
from typing import Callable, Optional

def sha256d(b: bytes) -> bytes:
    """Double SHA-256 hash."""
    return hashlib.sha256(hashlib.sha256(b).digest()).digest()

def calculate_merkle_root(coinbase_hash: bytes, merkle_branches: list[str]) -> bytes:
    """Calculates the 32-byte Merkle root from Coinbase hash and branch hashes."""
    current = coinbase_hash
    for b_hex in merkle_branches:
        branch = binascii.unhexlify(b_hex)
        current = sha256d(current + branch)
    return current

def diff_to_target(difficulty: float) -> int:
    """
    Converts pool difficulty to a 256-bit integer target.
    True diff 1 target for Bitcoin/Litecoin/Monacoin Lyra2REv2:
    0x00000000ffff0000000000000000000000000000000000000000000000000000
    """
    if difficulty <= 0:
        difficulty = 0.0001
    max_target = 0x00000000FFFF0000000000000000000000000000000000000000000000000000
    target = int(max_target / difficulty)
    return target

class StratumJob:
    def __init__(self, job_id: str, prevhash: str, coinb1: str, coinb2: str,
                 merkle_branches: list[str], version: str, nbits: str, ntime: str, clean_jobs: bool):
        self.job_id = job_id
        self.prevhash = prevhash
        self.coinb1 = coinb1
        self.coinb2 = coinb2
        self.merkle_branches = merkle_branches
        self.version = version
        self.nbits = nbits
        self.ntime = ntime
        self.clean_jobs = clean_jobs

    def build_header_prefix(self, extranonce1: str, extranonce2: str) -> bytes:
        """
        Builds the first 76 bytes of the 80-byte block header.
        (Last 4 bytes will be the 32-bit uint nonce searched by GPU).
        """
        coinbase_tx = (
            binascii.unhexlify(self.coinb1) +
            binascii.unhexlify(extranonce1) +
            binascii.unhexlify(extranonce2) +
            binascii.unhexlify(self.coinb2)
        )
        coinbase_hash = sha256d(coinbase_tx)
        merkle_root = calculate_merkle_root(coinbase_hash, self.merkle_branches)

        # Reverse 32-bit words for prevhash and merkle_root (Bitcoin standard)
        def swap32_bytes(data: bytes) -> bytes:
            res = bytearray()
            for i in range(0, len(data), 4):
                res += data[i:i+4][::-1]
            return bytes(res)

        v_bytes = binascii.unhexlify(self.version)[::-1]
        p_bytes = swap32_bytes(binascii.unhexlify(self.prevhash))
        m_bytes = merkle_root
        t_bytes = binascii.unhexlify(self.ntime)[::-1]
        b_bytes = binascii.unhexlify(self.nbits)[::-1]

        header_76 = v_bytes + p_bytes + m_bytes + t_bytes + b_bytes
        return header_76

class StratumClient:
    def __init__(self, host: str, port: int, username: str, password: str = "x",
                 on_log: Optional[Callable[[str, str], None]] = None,
                 on_new_job: Optional[Callable[[StratumJob, int], None]] = None):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.on_log = on_log or (lambda msg, lvl: None)
        self.on_new_job = on_new_job or (lambda job, target: None)

        self.sock: Optional[socket.socket] = None
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self.extranonce1 = ""
        self.extranonce2_size = 4
        self.extranonce2_counter = 0
        self.difficulty = 0.05
        self.target = diff_to_target(self.difficulty)
        self.current_job: Optional[StratumJob] = None
        self.req_id = 1
        self.pending_submits = {}

    def log(self, msg: str, level: str = "info"):
        self.on_log(msg, level)

    def connect(self) -> bool:
        try:
            self.log(f"Stratum 接続試行: {self.host}:{self.port} ...", "info")
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.settimeout(15.0)
            self.sock.connect((self.host, self.port))
            self.sock.settimeout(None)
            self._running = True

            # Start listener thread
            self._thread = threading.Thread(target=self._listen_loop, daemon=True)
            self._thread.start()

            # 1. Subscribe
            self._send({
                "id": self._next_id(),
                "method": "mining.subscribe",
                "params": ["MonaMinerNative/1.4.0"]
            })
            return True
        except Exception as e:
            self.log(f"Stratum 接続失敗: {e}", "error")
            return False

    def _next_id(self) -> int:
        i = self.req_id
        self.req_id += 1
        return i

    def _send(self, data: dict):
        if not self.sock:
            return
        payload = json.dumps(data) + "\n"
        try:
            self.sock.sendall(payload.encode("utf-8"))
        except Exception as e:
            self.log(f"Stratum 送信エラー: {e}", "error")

    def submit_share(self, job_id: str, extranonce2: str, ntime: str, nonce_uint: int, callback=None):
        nonce_hex = f"{nonce_uint:08x}"
        # Reverse to little-endian hex bytes if necessary
        req_id = self._next_id()
        if callback:
            self.pending_submits[req_id] = callback

        self._send({
            "id": req_id,
            "method": "mining.submit",
            "params": [
                self.username,
                job_id,
                extranonce2,
                ntime,
                nonce_hex
            ]
        })
        self.log(f"★ Share 提出: Job {job_id} | Nonce: 0x{nonce_hex}", "info")

    def _listen_loop(self):
        buf = ""
        while self._running and self.sock:
            try:
                data = self.sock.recv(4096)
                if not data:
                    self.log("Stratum 接続がサーバーにより切断されました。", "warn")
                    break
                buf += data.decode("utf-8", errors="ignore")
                while "\n" in buf:
                    line, buf = buf.split("\n", 1)
                    line = line.strip()
                    if line:
                        self._handle_message(line)
            except Exception as e:
                if self._running:
                    self.log(f"Stratum 受信ループエラー: {e}", "error")
                break
        self._running = False

    def _handle_message(self, line: str):
        try:
            msg = json.loads(line)
        except Exception:
            return

        method = msg.get("method")
        msg_id = msg.get("id")
        result = msg.get("result")
        error = msg.get("error")

        if msg_id in self.pending_submits:
            cb = self.pending_submits.pop(msg_id)
            is_ok = bool(result is True and not error)
            cb(is_ok, error)
            if is_ok:
                self.log("✓ Share がプールに承認されました！ (Accepted)", "success")
            else:
                self.log(f"✗ Share が拒絶されました (Rejected): {error}", "error")
            return

        # 1. Subscribe response
        if msg_id == 1 and result:
            try:
                self.extranonce1 = result[1]
                self.extranonce2_size = result[2]
                self.log(f"Stratum Subscribe成功: ExtraNonce1={self.extranonce1}, EN2_Size={self.extranonce2_size}", "success")
                # 2. Authorize
                self._send({
                    "id": self._next_id(),
                    "method": "mining.authorize",
                    "params": [self.username, self.password]
                })
            except Exception as e:
                self.log(f"Subscribe解析エラー: {e}", "error")

        # 2. Authorize response
        elif msg_id == 2:
            if result:
                self.log(f"Stratum 認証成功: ワーカー '{self.username}'", "success")
            else:
                self.log(f"Stratum 認証拒絶: プールに拒絶されました (送信ユーザー名: '{self.username}')", "error")
                if "vippool" in self.host.lower():
                    self.log("💡 VIPPOOLヒント: VIPPOOLはWeb登録制プールです。Web(vippool.net)で登録した『アカウント名.ワーカー名』を入力してください。", "warn")

        # 3. Notification: set_difficulty
        elif method == "mining.set_difficulty":
            params = msg.get("params", [0.05])
            if params:
                self.difficulty = float(params[0])
                self.target = diff_to_target(self.difficulty)
                self.log(f"難易度更新 (Diff): {self.difficulty:.4f} (Target: {self.target:064x})", "info")

        # 4. Notification: mining.notify
        elif method == "mining.notify":
            params = msg.get("params", [])
            if len(params) >= 9:
                job = StratumJob(
                    job_id=params[0],
                    prevhash=params[1],
                    coinb1=params[2],
                    coinb2=params[3],
                    merkle_branches=params[4],
                    version=params[5],
                    nbits=params[6],
                    ntime=params[7],
                    clean_jobs=params[8]
                )
                self.current_job = job
                self.on_new_job(job, self.target)

    def close(self):
        self._running = False
        if self.sock:
            try:
                self.sock.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None
