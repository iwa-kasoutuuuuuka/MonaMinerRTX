"""
Tests for the small services (no GPU needed):
    python -m unittest tests.test_services -v
"""
import base64
import ctypes
import http.client
import http.server
import json
import os
import socket
import sys
import threading
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QCoreApplication

from app.services import idle_tracker
from app.services.node_service import fetch_node_sync_info
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


class _FakeRpcHandler(http.server.BaseHTTPRequestHandler):
    """Answers like Monacoin Core: 401 without the right Basic auth, JSON otherwise."""
    reply = (200, {"result": {}, "error": None})

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        expected = "Basic " + base64.b64encode(b"monacoinrpc:rpcpassword").decode()
        if self.headers.get("Authorization") != expected:
            self.send_response(401)
            self.end_headers()
            return
        code, body = self.reply
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


class TestNodeSyncInfo(unittest.TestCase):
    def setUp(self):
        self.httpd = http.server.HTTPServer(("127.0.0.1", 0), _FakeRpcHandler)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()

    def _fetch(self, reply, password="rpcpassword"):
        _FakeRpcHandler.reply = reply
        return fetch_node_sync_info("127.0.0.1", self.port, "monacoinrpc", password, timeout=3)

    def test_syncing_node(self):
        info = self._fetch((200, {"result": {"chain": "main", "blocks": 3_000_000, "headers": 4_000_000,
                                             "initialblockdownload": True}, "error": None}))
        self.assertTrue(info["is_running"])
        self.assertTrue(info["ibd"])
        self.assertEqual((info["blocks"], info["headers"]), (3_000_000, 4_000_000))
        self.assertAlmostEqual(info["progress"], 75.0)

    def test_wrong_password_is_not_reported_as_stopped(self):
        info = self._fetch((200, {}), password="wrong")
        self.assertTrue(info["is_running"])
        self.assertTrue(info["auth_error"])

    def test_loading_block_index(self):
        info = self._fetch((500, {"result": None, "error": {"code": -28, "message": "Loading block index..."}}))
        self.assertTrue(info["is_running"])
        self.assertTrue(info["is_loading"])
        self.assertIn("Loading block index", info["status_text"])

    def test_busy_node_that_does_not_answer_counts_as_running(self):
        """A node stuck in header sync can accept the TCP connection yet not answer within the timeout."""
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        s.listen(5)   # never accept()/reply: the request is sent, the read times out
        try:
            info = fetch_node_sync_info("127.0.0.1", s.getsockname()[1], timeout=0.5)
        finally:
            s.close()
        self.assertTrue(info["is_running"])
        self.assertTrue(info["is_loading"])

    def test_nothing_listening(self):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        info = fetch_node_sync_info("127.0.0.1", port, timeout=1)
        self.assertFalse(info["is_running"])
        self.assertEqual(info["port"], port)


if __name__ == "__main__":
    unittest.main()
