"""MCP server (mcp_server.py): JSON-RPC handling and the bridge to the dashboard API."""
import json
import os
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import mcp_server


class _FakeDashboard(BaseHTTPRequestHandler):
    state = {"is_mining": False, "posts": []}

    def log_message(self, *args):
        return

    def _send(self, obj):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._send({"is_mining": self.state["is_mining"], "hashrate_mhs": 290.0,
                    "recent_logs": [f"line {i}" for i in range(10)]})

    def do_POST(self):
        self.state["posts"].append(self.path)
        self.state["is_mining"] = self.path == "/api/start"
        self._send({"success": True})


def call(method, params=None, req_id=1):
    msg = {"jsonrpc": "2.0", "id": req_id, "method": method}
    if params is not None:
        msg["params"] = params
    return mcp_server.handle(msg)


def tool(name, arguments=None):
    res = call("tools/call", {"name": name, "arguments": arguments or {}})["result"]
    return res["isError"], res["content"][0]["text"]


class TestMcpServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), _FakeDashboard)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.url = f"http://127.0.0.1:{cls.httpd.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def setUp(self):
        os.environ["MONAMINER_URL"] = self.url
        _FakeDashboard.state.update(is_mining=False, posts=[])

    def tearDown(self):
        os.environ.pop("MONAMINER_URL", None)

    def test_initialize_echoes_supported_version_and_offers_latest_otherwise(self):
        res = call("initialize", {"protocolVersion": "2024-11-05"})["result"]
        self.assertEqual(res["protocolVersion"], "2024-11-05")
        self.assertIn("tools", res["capabilities"])
        res = call("initialize", {"protocolVersion": "1999-01-01"})["result"]
        self.assertEqual(res["protocolVersion"], mcp_server.SUPPORTED_PROTOCOLS[0])

    def test_notifications_get_no_response(self):
        self.assertIsNone(mcp_server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}))

    def test_tools_list_matches_handlers(self):
        tools = call("tools/list")["result"]["tools"]
        self.assertEqual({t["name"] for t in tools}, set(mcp_server.HANDLERS))
        for t in tools:
            self.assertEqual(t["inputSchema"]["type"], "object")

    def test_status_has_no_log_lines(self):
        is_error, text = tool("get_status")
        self.assertFalse(is_error)
        data = json.loads(text)
        self.assertEqual(data["hashrate_mhs"], 290.0)
        self.assertNotIn("recent_logs", data)

    def test_logs_returns_newest_lines(self):
        is_error, text = tool("get_logs", {"lines": 3})
        self.assertFalse(is_error)
        self.assertEqual(json.loads(text)["lines"], ["line 7", "line 8", "line 9"])
        self.assertTrue(tool("get_logs", {"lines": 0})[0])
        self.assertTrue(tool("get_logs", {"lines": "3"})[0])

    def test_start_and_stop_only_post_when_state_changes(self):
        self.assertTrue(json.loads(tool("start_mining")[1])["changed"])
        self.assertFalse(json.loads(tool("start_mining")[1])["changed"])
        self.assertTrue(json.loads(tool("stop_mining")[1])["changed"])
        self.assertFalse(json.loads(tool("stop_mining")[1])["changed"])
        self.assertEqual(_FakeDashboard.state["posts"], ["/api/start", "/api/stop"])

    def test_app_not_running_is_a_tool_error_not_a_crash(self):
        os.environ["MONAMINER_URL"] = "http://127.0.0.1:9"     # nothing listens there
        is_error, text = tool("get_status")
        self.assertTrue(is_error)
        self.assertIn("接続できません", text)

    def test_unknown_tool_and_method(self):
        self.assertEqual(call("tools/call", {"name": "nope"})["error"]["code"], -32602)
        self.assertEqual(call("nope")["error"]["code"], -32601)
        self.assertEqual(call("ping")["result"], {})


if __name__ == "__main__":
    unittest.main()
