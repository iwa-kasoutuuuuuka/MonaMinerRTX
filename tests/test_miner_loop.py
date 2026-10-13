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


class TestSoloConnectWaitsForWarmup(unittest.TestCase):
    """A node that was just started answers "Loading block index..." (-28) for a while."""

    class WarmingClient:
        def __init__(self, warm_calls, final):
            self.warm_calls = warm_calls
            self.final = final
            self.calls = 0
            self.node_warming_up = False

        def test_connection(self):
            self.calls += 1
            self.node_warming_up = self.calls <= self.warm_calls
            if self.node_warming_up:
                return False, "RPC接続エラー: Loading block index...", {}
            return self.final

    def _connect(self, client):
        import app.miner.opencl_miner as om
        worker = OpenCLMinerWorker("eco", "solo", "cpu", "", "addr", "w", cpu_threads=1, hardware_mgr=FakeHardware())
        logs = []
        worker.log_message.connect(lambda text, level: logs.append((text, level)), Qt.DirectConnection)
        real_client, real_poll = om.RpcSoloClient, om.NODE_WARMUP_POLL_S
        om.RpcSoloClient = lambda **kwargs: client
        om.NODE_WARMUP_POLL_S = 0.01
        try:
            return worker._connect(), logs
        finally:
            om.RpcSoloClient, om.NODE_WARMUP_POLL_S = real_client, real_poll

    def test_waits_until_the_node_finished_starting(self):
        client = self.WarmingClient(3, (True, "接続成功", {}))
        ok, logs = self._connect(client)
        self.assertTrue(ok)
        self.assertEqual(client.calls, 4)
        self.assertEqual(len([t for t, _ in logs if "起動処理中" in t]), 1)  # announced once, not per retry
        self.assertFalse([t for t, level in logs if level == "error"])

    def test_other_errors_still_fail_at_once(self):
        client = self.WarmingClient(0, (False, "RPC接続エラー: refused", {}))
        ok, logs = self._connect(client)
        self.assertFalse(ok)
        self.assertEqual(client.calls, 1)

    def test_error_after_warmup_fails(self):
        client = self.WarmingClient(2, (False, "RPC接続エラー: Incorrect password", {}))
        ok, _ = self._connect(client)
        self.assertFalse(ok)
        self.assertEqual(client.calls, 3)


if __name__ == "__main__":
    unittest.main()


class TestGpuMineLoop(unittest.TestCase):
    """The GPU launch queue (needs an OpenCL GPU; skipped otherwise): found nonces are submitted,
    launches of an outdated template are dropped, and the worker stops cleanly."""

    @classmethod
    def setUpClass(cls):
        try:
            from app.miner.opencl_backend import OpenCLBackend
            if not OpenCLBackend.get_all_gpu_devices():
                raise unittest.SkipTest("no OpenCL GPU")
        except Exception as e:
            raise unittest.SkipTest(f"OpenCL unavailable: {e}")
        QCoreApplication.instance() or QCoreApplication([])

    def _run(self, device_target):
        node = FakeNode()
        worker = OpenCLMinerWorker("eco", "solo", device_target, "", "addr", "w",
                                   cpu_threads=2, hardware_mgr=FakeHardware(), selected_gpu_indices=[0])
        logs = []
        worker.log_message.connect(lambda text, level: logs.append((level, text)), Qt.DirectConnection)
        worker.solo_client = node
        worker._connect = lambda: True
        worker.start()
        time.sleep(4.0)
        worker.stop()
        self.assertTrue(worker.wait(5000))
        self.assertEqual([t for l, t in logs if l == "error"], [])
        self.assertTrue(any("GPU #" in t for l, t in logs), "no GPU find was reported")
        self.assertGreater(node.accepted, 0)
        self.assertEqual(node.stale, 0)
        self.assertEqual(worker.rejected_shares, 0)

    def test_gpu_only(self):
        self._run("gpu")

    def test_hybrid(self):
        self._run("hybrid")
