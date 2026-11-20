"""External miner process handling (hashrate units, no orphan process) and config file recovery."""
import json
import os
import sys
import tempfile
import threading
import time
import unittest

from app.config import ConfigManager
from app.miner_controller import ProcessWorker


class _FakeHardware:
    def get_live_metrics(self):
        return {"power_w": 100.0}


def _worker(script: str) -> ProcessWorker:
    return ProcessWorker(sys.executable, ["-u", "-c", script], _FakeHardware())


class TestProcessWorkerHashrateUnits(unittest.TestCase):
    def test_units_are_converted_to_mhs(self):
        lines = ["GPU #0: 950.00 kH/s", "GPU #0: 61.5 MH/s", "Total: 1.25 GH/s", "cpu: 500 H/s"]
        w = _worker("\n".join(f"print({line!r})" for line in lines))
        seen = []
        w.hashrate_update.connect(lambda mhs, pwr, eff: seen.append(mhs))
        w.run()
        self.assertEqual(len(seen), 4)
        for got, want in zip(seen, [0.95, 61.5, 1250.0, 0.0005]):
            self.assertAlmostEqual(got, want, places=6)


class TestProcessWorkerNeverLeavesMinerRunning(unittest.TestCase):
    ENDLESS = "import time\nwhile True:\n    print('GPU #0: 10 MH/s', flush=True)\n    time.sleep(0.05)"

    def test_stop_requested_before_process_started(self):
        w = _worker(self.ENDLESS)
        w._running = False               # stop() ran while Popen was still in flight
        t = threading.Thread(target=w.run, daemon=True)
        t.start()
        t.join(15)
        self.assertFalse(t.is_alive(), "run() kept waiting on a miner nobody will stop")
        self.assertIsNotNone(w.process.poll(), "external miner left running")

    def test_stop_while_running(self):
        w = _worker(self.ENDLESS)
        t = threading.Thread(target=w.run, daemon=True)
        t.start()
        deadline = time.time() + 10
        while w.process is None and time.time() < deadline:
            time.sleep(0.02)
        self.assertIsNotNone(w.process)
        time.sleep(0.3)                  # let it read a few lines
        self.assertIsNone(w.process.poll())
        w._running = False
        w._kill_process()
        t.join(15)
        self.assertFalse(t.is_alive())
        self.assertIsNotNone(w.process.poll())


class TestConfigRecovery(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.dir.name, "config.json")

    def tearDown(self):
        self.dir.cleanup()

    def test_unreadable_config_is_kept_not_overwritten(self):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write('{"wallet_address": "MABC", "cpu_thr')      # cut off mid-write
        cfg = ConfigManager(self.path)
        self.assertIsNotNone(cfg.load_error)
        cfg.set("cpu_threads", 4)                               # rewrites config.json from defaults
        with open(self.path + ".corrupt", encoding="utf-8") as f:
            self.assertIn("MABC", f.read())
        with open(self.path, encoding="utf-8") as f:
            self.assertEqual(json.load(f)["cpu_threads"], 4)

    def test_non_object_root_is_rejected(self):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("[1, 2, 3]")
        cfg = ConfigManager(self.path)
        self.assertIsNotNone(cfg.load_error)
        self.assertEqual(cfg.get("solo_port"), 9402)

    def test_good_config_loads_without_error(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump({"cpu_threads": 7, "config_version": 2}, f)
        cfg = ConfigManager(self.path)
        self.assertIsNone(cfg.load_error)
        self.assertEqual(cfg.get("cpu_threads"), 7)
        self.assertFalse(os.path.exists(self.path + ".corrupt"))


if __name__ == "__main__":
    unittest.main()
