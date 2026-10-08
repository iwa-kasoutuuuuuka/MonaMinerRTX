"""
Tests for the solo mining loop of the built-in engine (CPU only, fake node, no GPU needed):
    python -m unittest tests.test_miner_loop -v
"""
import os
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QCoreApplication, Qt

from app.miner.cpu_backend import CpuBackend, CpuBackendUnavailable
from app.miner.opencl_miner import OpenCLMinerWorker
from app.miner.rpc_solo_client import SoloBlockTemplate


class FakeHardware:
    def get_mode_recommendation(self):
        return {"modes": {"eco": {"intensity": 18, "target_pwr_w": 200.0}}}

    def get_live_metrics(self):
        return {"power_w": 0.0}


class FakeNode:
    """Stands in for RpcSoloClient: a regtest-like chain where about every second nonce is a block."""
    address_invalid = False

    def __init__(self, down=False):
        self.down = down
        self.height = 100
        self.accepted = 0
        self.stale = 0
        self.lock = threading.Lock()

    def _tip(self):
        return f"{self.height:064x}"

    def test_connection(self):
        return True, "fake", {}

    def get_block_template(self):
        if self.down:
            return None, "getblocktemplate 取得エラー: node is down"
        gbt = {
            "height": self.height + 1, "version": 0x20000000, "previousblockhash": self._tip(),
            "bits": "207fffff", "curtime": int(time.time()), "coinbasevalue": 2500000000,
            "target": "7fffff" + "0" * 58, "transactions": [],
        }
        return SoloBlockTemplate(gbt, b"\x51", "addr"), None

    def submit_block(self, tpl, nonce):
        with self.lock:
            if tpl.prev_hash_hex != self._tip():
                self.stale += 1
                return False, "inconclusive"
            self.height += 1
            self.accepted += 1
            return True, "ok"


class TestSoloMineLoop(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            CpuBackend.load()
        except CpuBackendUnavailable as e:
            raise unittest.SkipTest(f"native CPU engine unavailable: {e}")
        QCoreApplication.instance() or QCoreApplication([])

    def _run(self, node, seconds):
        worker = OpenCLMinerWorker("eco", "solo", "cpu", "", "addr", "w",
                                   cpu_threads=4, hardware_mgr=FakeHardware())
        logs = []
        # direct: no event loop runs here to deliver queued signals from the worker thread
        worker.log_message.connect(lambda text, level: logs.append(text), Qt.DirectConnection)

        def connect():
            worker.solo_client = node
            return True

        worker._connect = connect
        worker.start()
        time.sleep(seconds)
        worker.stop()
        self.assertTrue(worker.wait(5000))
        return worker, logs

    def test_scans_of_an_old_template_are_not_submitted(self):
        node = FakeNode()
        worker, _ = self._run(node, 2.0)
        self.assertGreater(node.accepted, 0)
        self.assertEqual(node.stale, 0)
        self.assertEqual(worker.rejected_shares, 0)

    def test_unchanged_rpc_error_is_not_logged_on_every_retry(self):
        node = FakeNode(down=True)
        _, logs = self._run(node, 2.0)  # ~4 retries
        self.assertEqual(len([line for line in logs if "node is down" in line]), 1)


if __name__ == "__main__":
    unittest.main()
