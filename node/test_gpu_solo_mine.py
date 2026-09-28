import subprocess, time, os, urllib.request, json, base64, struct, hashlib, sys
from ctypes import c_uint

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

dir1 = os.path.abspath('node/regtest_data/n1')
dir2 = os.path.abspath('node/regtest_data/n2')
bin_path = os.path.abspath('node/bin/monacoind.exe')
p1 = subprocess.Popen([bin_path, f'-datadir={dir1}', '-regtest', '-server=1', '-rpcuser=monacoinrpc', '-rpcpassword=rpcpassword', '-rpcport=9402', '-fallbackfee=0.0001'])
p2 = subprocess.Popen([bin_path, f'-datadir={dir2}', '-regtest', '-server=1', '-rpcuser=monacoinrpc', '-rpcpassword=rpcpassword', '-rpcport=9403', '-port=20445', '-addnode=127.0.0.1:20444', '-fallbackfee=0.0001'])
time.sleep(3)

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
    target_high = (int(gbt['target'], 16) >> 224) & 0xffffffff
    print(f'GBT Height: {height}, Target High: 0x{target_high:08x}')

    addr = rpc(9402, 'getnewaddress')['result']
    val_info = rpc(9402, 'validateaddress', [addr])['result']
    script_pubkey = bytes.fromhex(val_info['scriptPubKey'])

    scriptsig = bytes([1, height]) + b'/MonaMinerRTX-GPU/'
    tx = bytearray()
    tx += struct.pack('<i', 1)
    tx += encode_varint(1)
    tx += b'\x00' * 32
    tx += struct.pack('<I', 0xffffffff)
    tx += encode_varint(len(scriptsig))
    tx += scriptsig
    tx += struct.pack('<I', 0xffffffff)

    has_witness = 'default_witness_commitment' in gbt and gbt['default_witness_commitment']
    tx += encode_varint(2 if has_witness else 1)
    tx += struct.pack('<Q', gbt['coinbasevalue'])
    tx += encode_varint(len(script_pubkey))
    tx += script_pubkey
    if has_witness:
        w_script = bytes.fromhex(gbt['default_witness_commitment'])
        tx += struct.pack('<Q', 0)
        tx += encode_varint(len(w_script))
        tx += w_script
    tx += struct.pack('<I', 0)
    cb_tx_bytes = bytes(tx)
    cb_hash = sha256d(cb_tx_bytes)

    m_root = cb_hash

    hdr_prefix = bytearray()
    hdr_prefix += struct.pack('<i', gbt['version'])
    hdr_prefix += bytes.fromhex(gbt['previousblockhash'])[::-1]
    hdr_prefix += m_root
    hdr_prefix += struct.pack('<I', gbt['curtime'])
    hdr_prefix += bytes.fromhex(gbt['bits'])[::-1]
    header_76 = bytes(hdr_prefix)

    # Use OpenCL to mine nonce
    from app.miner.opencl_backend import OpenCLBackend, OpenCLContext
    plat = OpenCLBackend.get_platforms()[0]
    dev = OpenCLBackend.get_devices(plat['id'])[0]
    dev_name = dev['name']
    print(f'Mining with GPU: {dev_name}...')

    ctx = OpenCLContext(plat['id'], dev['id'])
    with open('app/miner/kernels/lyra2v2.cl', 'r', encoding='utf-8') as f:
        ctx.build_program(f.read())
    kernel = ctx.get_kernel('search_lyra2v2')

    buf_header = ctx.create_buffer(19 * 4)
    buf_found_nonce = ctx.create_buffer(4)
    buf_found_count = ctx.create_buffer(4)

    c_header = (c_uint * 19).from_buffer_copy(header_76)
    ctx.write_buffer(buf_header, c_header, 19 * 4)
    ctx.write_buffer(buf_found_count, (c_uint * 1)(0), 4)

    ctx.set_arg_mem(kernel, 0, buf_header)
    ctx.set_arg_uint(kernel, 1, 0)
    ctx.set_arg_uint(kernel, 2, target_high)
    ctx.set_arg_mem(kernel, 3, buf_found_nonce)
    ctx.set_arg_mem(kernel, 4, buf_found_count)

    ctx.run_kernel_1d(kernel, 65536, 128)
    ctx.finish()

    c_cnt = (c_uint * 1)(0)
    ctx.read_buffer(buf_found_count, c_cnt, 4)
    print(f'Nonces found: {c_cnt[0]}')

    c_nonce = (c_uint * 1)(0)
    ctx.read_buffer(buf_found_nonce, c_nonce, 4)
    found_nonce = c_nonce[0]
    print(f'Found Nonce: 0x{found_nonce:08x}')

    # Assemble full block with found nonce
    hdr = header_76 + struct.pack('<I', found_nonce)
    block = hdr + encode_varint(1) + cb_tx_bytes
    block_hex = block.hex()

    sub_res = rpc(9402, 'submitblock', [block_hex])
    print('*** SUBMITBLOCK RESULT ***:', sub_res)

    info = rpc(9402, 'getblockchaininfo')['result']
    print('*** NEW BLOCKCHAIN HEIGHT ***:', info['blocks'])
    print('*** BEST BLOCK HASH ***:', info['bestblockhash'])
finally:
    for port in [9402, 9403]:
        try:
            rpc(port, 'stop')
        except Exception:
            pass
    p1.wait(5)
    p2.wait(5)
