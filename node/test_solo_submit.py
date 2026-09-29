"""
Tests only the *submit path* (no GPU): builds a block from getblocktemplate with the app's own
RpcSoloClient, tries nonces 0, 1, 2 ... and lets Monacoin Core's regtest PoW check decide.
The block is accepted as soon as a nonce beats the (very easy) regtest target.

Run from anywhere:  python node/test_solo_submit.py
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app.miner.rpc_solo_client import RpcSoloClient

REWARD_ADDRESS = "rmona1q3vdvha77mhqlvrq374fp45rcgz02ah2yn22hww"


def main() -> int:
    exe = os.path.join(ROOT, "node", "bin", "monacoind.exe")
    workdir = tempfile.mkdtemp(prefix="mona_regtest_")
    procs = []
    for i, (rpc, p2p, extra) in enumerate(((19402, 29444, ["-listen=1"]), (19403, 29445, ["-addnode=127.0.0.1:29444"]))):
        datadir = os.path.join(workdir, f"n{i + 1}")
        os.makedirs(datadir)
        procs.append(subprocess.Popen(
            [exe, f"-datadir={datadir}", "-regtest", "-server=1", "-rpcuser=u", "-rpcpassword=p",
             f"-rpcport={rpc}", f"-port={p2p}", "-fallbackfee=0.0001", *extra],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    node = RpcSoloClient("127.0.0.1", 19402, "u", "p", wallet_address=REWARD_ADDRESS)
    try:
        for _ in range(60):
            if node.call("getblockchaininfo").get("result"):
                break
            time.sleep(0.5)
        for _ in range(40):
            if node.call("getnetworkinfo")["result"]["connections"] >= 1:
                break
            time.sleep(0.5)

        # a brand-new regtest chain is in "initial sync" until it has a block
        node.call("generatetoaddress", [1, REWARD_ADDRESS])
        tpl, err = node.get_block_template()
        if not tpl:
            print("getblocktemplate failed:", err)
            return 2
        print(f"template for height {tpl.height}")
        for nonce in range(256):
            ok, msg = node.submit_block(tpl, nonce)
            if ok:
                print(f"nonce {nonce}: {msg}")
                height = node.call("getblockchaininfo")["result"]["blocks"]
                print("chain height on Monacoin Core:", height)
                print("RESULT:", "PASS" if height == tpl.height else "FAIL")
                return 0 if height == tpl.height else 1
            if "high-hash" not in msg:  # anything but a failed PoW check is a real problem
                print(f"nonce {nonce}: unexpected rejection: {msg}")
                print("RESULT: FAIL")
                return 1
        print("no nonce below 256 was accepted (extremely unlikely)")
        return 1
    finally:
        for port in (19402, 19403):
            try:
                RpcSoloClient("127.0.0.1", port, "u", "p").call("stop")
            except Exception:
                pass
        for p in procs:
            try:
                p.wait(20)
            except Exception:
                p.kill()
        shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    sys.exit(main())
