"""
End-to-end solo mining test on a private regtest chain:
  Monacoin Core (2 regtest nodes)  <--RPC-->  OpenCLMinerWorker (the app's GPU engine)

Every block the GPU finds is validated by the real Monacoin Core (`submitblock`), so a green run
proves that the kernel, the coinbase/merkle/header builder and the submit path are all correct.

Run from anywhere:  python node/test_gpu_solo_mine.py [blocks] [gpu|cpu|hybrid]   (default: 3 blocks, gpu)
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PySide6.QtCore import QCoreApplication, Qt

from app.hardware import HardwareManager
from app.miner.opencl_miner import OpenCLMinerWorker
from app.miner.rpc_solo_client import RpcSoloClient

RPC1, RPC2, P2P1, P2P2 = 19402, 19403, 29444, 29445
# Monacoin's regtest checks PoW with scrypt below this height and with Lyra2REv2 from it on.
LYRA2_MIN_HEIGHT = 61
# any valid regtest address works as a coinbase destination (the node validates it via RPC)
REWARD_ADDRESS = "rmona1q3vdvha77mhqlvrq374fp45rcgz02ah2yn22hww"


def start_node(exe, datadir, rpc_port, p2p_port, extra=()):
    return subprocess.Popen(
        [exe, f"-datadir={datadir}", "-regtest", "-server=1", "-rpcuser=u", "-rpcpassword=p",
         f"-rpcport={rpc_port}", f"-port={p2p_port}", "-fallbackfee=0.0001", *extra],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main(blocks_wanted: int, device: str = "gpu") -> int:
    exe = os.path.join(ROOT, "node", "bin", "monacoind.exe")
    workdir = tempfile.mkdtemp(prefix="mona_regtest_")
    d1, d2 = os.path.join(workdir, "n1"), os.path.join(workdir, "n2")
    os.makedirs(d1)
    os.makedirs(d2)
    procs = [start_node(exe, d1, RPC1, P2P1, ["-listen=1"]),
             start_node(exe, d2, RPC2, P2P2, [f"-addnode=127.0.0.1:{P2P1}"])]
    node = RpcSoloClient("127.0.0.1", RPC1, "u", "p")
    app = QCoreApplication([])
    worker = None
    try:
        for _ in range(60):
            if node.call("getblockchaininfo").get("result"):
                break
            time.sleep(0.5)
        else:
            print("node did not start")
            return 2
        for _ in range(40):  # getblocktemplate needs at least one peer
            if node.call("getnetworkinfo")["result"]["connections"] >= 1:
                break
            time.sleep(0.5)

        node.call("generatetoaddress", [LYRA2_MIN_HEIGHT, REWARD_ADDRESS], timeout=120)
        start_height = node.call("getblockchaininfo")["result"]["blocks"]
        print(f"chain prepared, height {start_height}; mining {blocks_wanted} block(s) with device={device} ...")

        worker = OpenCLMinerWorker("eco", "solo", device, "", REWARD_ADDRESS, "test",
                                   solo_host="127.0.0.1", solo_port=RPC1, solo_user="u", solo_pass="p",
                                   cpu_threads=8, hardware_mgr=HardwareManager(), selected_gpu_indices=[0])
        worker.log_message.connect(lambda text, level: print(f"  [{level}] {text}"), Qt.DirectConnection)
        worker.start()
        deadline = time.time() + 120
        while time.time() < deadline and worker.isRunning() and worker.accepted_shares < blocks_wanted:
            app.processEvents()
            time.sleep(0.1)
        worker.stop()

        height = node.call("getblockchaininfo")["result"]["blocks"]
        print(f"\naccepted by the node: {worker.accepted_shares}, rejected: {worker.rejected_shares}, "
              f"chain height {start_height} -> {height}")
        ok = worker.accepted_shares >= blocks_wanted and worker.rejected_shares == 0 \
            and height == start_height + worker.accepted_shares
        print("RESULT:", "PASS" if ok else "FAIL")
        return 0 if ok else 1
    finally:
        for port in (RPC1, RPC2):
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
    sys.exit(main(int(sys.argv[1]) if len(sys.argv) > 1 else 3, sys.argv[2] if len(sys.argv) > 2 else "gpu"))
