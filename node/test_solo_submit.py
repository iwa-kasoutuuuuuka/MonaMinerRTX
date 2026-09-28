import subprocess, time, os, urllib.request, json, base64, struct, hashlib

dir1 = os.path.abspath('node/regtest_data/n1')
bin_path = os.path.abspath('node/bin/monacoind.exe')
p1 = subprocess.Popen([bin_path, f'-datadir={dir1}', '-regtest', '-server=1', '-rpcuser=monacoinrpc', '-rpcpassword=rpcpassword', '-rpcport=9402', '-fallbackfee=0.0001'])
time.sleep(2)

dir2 = os.path.abspath('node/regtest_data/n2')
p2 = subprocess.Popen([bin_path, f'-datadir={dir2}', '-regtest', '-server=1', '-rpcuser=monacoinrpc', '-rpcpassword=rpcpassword', '-rpcport=9403', '-port=20445', '-addnode=127.0.0.1:20444', '-fallbackfee=0.0001'])
time.sleep(2)

def rpc(port, method, params=[]):
    payload = json.dumps({'jsonrpc': '1.0', 'id': 'test', 'method': method, 'params': params}).encode('utf-8')
    auth = base64.b64encode(b'monacoinrpc:rpcpassword').decode('ascii')
    req = urllib.request.Request(f'http://127.0.0.1:{port}/', data=payload, headers={'Authorization': f'Basic {auth}', 'Content-Type': 'application/json'})
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode('utf-8'))

def sha256d(b: bytes) -> bytes:
    return hashlib.sha256(hashlib.sha256(b).digest()).digest()

def encode_varint(n: int) -> bytes:
    if n < 0xfd:
        return bytes([n])
    elif n <= 0xffff:
        return b'\xfd' + struct.pack('<H', n)
    elif n <= 0xffffffff:
        return b'\xfe' + struct.pack('<I', n)
    else:
        return b'\xff' + struct.pack('<Q', n)

try:
    gbt = rpc(9402, 'getblocktemplate', [{'rules': ['segwit']}])['result']
    height = gbt['height']
    addr = rpc(9402, 'getnewaddress')['result']
    val_info = rpc(9402, 'validateaddress', [addr])['result']
    script_pubkey = bytes.fromhex(val_info['scriptPubKey'])

    # Build scriptSig with BIP34 height
    if height <= 16:
        height_script = bytes([1, height])
    elif height <= 127:
        height_script = bytes([1, height])
    elif height <= 255:
        height_script = bytes([2, height, 0])
    else:
        height_script = bytes([2, height & 0xff, (height >> 8) & 0xff])
    scriptsig = height_script + b'/MonaMinerRTX/'

    # Build coinbase tx
    tx = bytearray()
    tx += struct.pack('<i', 1) # version 1
    tx += encode_varint(1) # 1 input
    tx += b'\x00' * 32 # prevout hash
    tx += struct.pack('<I', 0xffffffff) # prevout n
    tx += encode_varint(len(scriptsig))
    tx += scriptsig
    tx += struct.pack('<I', 0xffffffff) # sequence

    # Outputs
    has_witness = 'default_witness_commitment' in gbt and gbt['default_witness_commitment']
    tx += encode_varint(2 if has_witness else 1)
    # Output 0: Reward
    tx += struct.pack('<Q', gbt['coinbasevalue'])
    tx += encode_varint(len(script_pubkey))
    tx += script_pubkey
    if has_witness:
        w_script = bytes.fromhex(gbt['default_witness_commitment'])
        tx += struct.pack('<Q', 0)
        tx += encode_varint(len(w_script))
        tx += w_script
    tx += struct.pack('<I', 0) # locktime

    cb_tx_bytes = bytes(tx)
    cb_hash = sha256d(cb_tx_bytes)

    # Merkle root
    tx_hashes = [cb_hash]
    for t in gbt.get('transactions', []):
        tx_hashes.append(bytes.fromhex(t['txid'])[::-1])
    
    current = tx_hashes
    while len(current) > 1:
        if len(current) % 2 != 0:
            current.append(current[-1])
        nxt = []
        for i in range(0, len(current), 2):
            nxt.append(sha256d(current[i] + current[i+1]))
        current = nxt
    m_root = current[0]

    # Header prefix (76 bytes)
    hdr_prefix = bytearray()
    hdr_prefix += struct.pack('<i', gbt['version'])
    hdr_prefix += bytes.fromhex(gbt['previousblockhash'])[::-1]
    hdr_prefix += m_root
    hdr_prefix += struct.pack('<I', gbt['curtime'])
    hdr_prefix += bytes.fromhex(gbt['bits'])[::-1]

    # Nonce
    nonce = 0
    hdr = hdr_prefix + struct.pack('<I', nonce)

    # Full block
    block = bytearray()
    block += hdr
    block += encode_varint(1 + len(gbt.get('transactions', [])))
    block += cb_tx_bytes
    for t in gbt.get('transactions', []):
        block += bytes.fromhex(t['data'])

    block_hex = block.hex()
    print(f'Submitting block (len {len(block)} bytes)...')
    sub_res = rpc(9402, 'submitblock', [block_hex])
    print('SUBMITBLOCK RESULT:', sub_res)

    info = rpc(9402, 'getblockchaininfo')['result']
    print('New block height on Monacoin Core:', info['blocks'])
    print('Best block hash:', info['bestblockhash'])
finally:
    for port in [9402, 9403]:
        try:
            rpc(port, 'stop')
        except Exception:
            pass
    p1.wait(5)
    p2.wait(5)
