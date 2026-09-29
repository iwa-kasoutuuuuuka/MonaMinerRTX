"""
Tests for the small services (no GPU needed):
    python -m unittest tests.test_services -v
"""
import ctypes
import http.client
import os
import sys
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QCoreApplication

from app.services import idle_tracker
from app.services.web_server import WebMonitoringServer


@unittest.skipUnless(sys.platform == "win32", "GetLastInputInfo is Windows only")
class TestIdleTrackerTickWrap(unittest.TestCase):
    """GetTickCount() is a 32-bit millisecond counter; ctypes returns it as a signed int."""

    def _idle_seconds(self, tick_count, last_input):
        def get_last_input_info(byref_obj):
            byref_obj._obj.dwTime = last_input
            return 1

        fake_windll = types.SimpleNamespace(
            user32=types.SimpleNamespace(GetLastInputInfo=get_last_input_info),
            kernel32=types.SimpleNamespace(GetTickCount=lambda: tick_count),
        )
        real = getattr(ctypes, "windll")
        ctypes.windll = fake_windll
        try:
            QCoreApplication.instance() or QCoreApplication([])
            return idle_tracker.IdleTracker().get_idle_seconds()
        finally:
            ctypes.windll = real

    def test_normal_uptime(self):
        self.assertEqual(self._idle_seconds(100_000, 40_000), 60.0)

    def test_uptime_beyond_24_9_days(self):
        # 30 days of uptime: GetTickCount() reads as a negative int through ctypes (c_int restype)
        tick_unsigned = 30 * 24 * 3600 * 1000 % (1 << 32)
        tick_signed = tick_unsigned - (1 << 32) if tick_unsigned >= 1 << 31 else tick_unsigned
        self.assertLess(tick_signed, 0)
        self.assertEqual(self._idle_seconds(tick_signed, tick_unsigned - 90_000), 90.0)

    def test_counter_wrap_around(self):
        # last input just before the 49.7 day wrap, tick count just after it
        self.assertEqual(self._idle_seconds(5_000, (1 << 32) - 5_000), 10.0)


class TestWebServerSecurity(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.server = WebMonitoringServer(host="127.0.0.1", port=0)
        self.server.start(lambda: {"is_mining": False},
                          lambda: self.calls.append("start"),
                          lambda: self.calls.append("stop"))
        self.port = self.server.server.server_address[1]

    def tearDown(self):
        self.server.stop()

    def _post(self, path, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("POST", path, headers=headers or {})
        status = conn.getresponse().status
        conn.close()
        return status

    def test_same_origin_and_plain_clients_may_control(self):
        self.assertEqual(self._post("/api/start"), 200)
        self.assertEqual(self._post("/api/stop", {"Origin": f"http://127.0.0.1:{self.port}"}), 200)
        self.assertEqual(self.calls, ["start", "stop"])

    def test_cross_site_post_is_rejected(self):
        self.assertEqual(self._post("/api/start", {"Origin": "http://evil.example"}), 403)
        self.assertEqual(self.calls, [])

    def test_status_has_no_wildcard_cors(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("GET", "/api/status")
        resp = conn.getresponse()
        resp.read()
        self.assertIsNone(resp.getheader("Access-Control-Allow-Origin"))
        conn.close()


if __name__ == "__main__":
    unittest.main()
