"""
MCP (Model Context Protocol) server for MonaMiner RTX.

Lets an MCP client (Claude Code, Antigravity, Claude Desktop, ...) read the miner's status and
start / stop mining. It is a thin bridge: the client talks JSON-RPC to this script over stdio, and
this script talks to the running application's web dashboard API (http://127.0.0.1:8888 by default).

    client  <-- stdio, JSON-RPC 2.0 -->  mcp_server.py  <-- HTTP -->  MonaMiner RTX (dashboard API)

Requirements: the MonaMiner RTX application is running with the web dashboard enabled (the default).
No third-party packages: standard library only, so it also runs without the app's dependencies.

Environment:
    MONAMINER_URL   dashboard base URL (default: http://127.0.0.1:<web_dashboard_port from config.json>)
"""
import json
import os
import sys
import urllib.error
import urllib.request

SERVER_NAME = "monaminer"
SERVER_VERSION = "2.2.4"
# Protocol revisions this server can speak. The client's requested version is echoed when it is one
# of these; otherwise the newest one here is offered and the client decides whether to continue.
SUPPORTED_PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")
HTTP_TIMEOUT_S = 8

TOOLS = [
    {
        "name": "get_status",
        "title": "採掘ステータス取得",
        "description": (
            "MonaMiner RTX の現在の状態を返します: 採掘中かどうか、ハッシュレート (MH/s)、消費電力 (W)、"
            "電力効率、GPU 温度、ファン回転率、承認/拒絶シェア数 (ソロでは発見ブロック数)、電気代の概算、稼働時間。"
        ),
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "get_logs",
        "title": "動作ログ取得",
        "description": "MonaMiner RTX の直近の動作ログ (新しいブロックテンプレート、発見した Nonce、エラーなど) を返します。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "lines": {"type": "integer", "minimum": 1, "maximum": 200, "default": 30,
                          "description": "返す行数 (新しい側から)。アプリが保持している行数が上限です。"},
            },
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "start_mining",
        "title": "採掘開始",
        "description": (
            "アプリに保存されている現在の設定 (プール/ソロ、GPU/CPU、モード) で採掘を開始します。"
            "すでに採掘中なら何もしません。GPU に高負荷がかかり電力を消費します。"
        ),
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
    },
    {
        "name": "stop_mining",
        "title": "採掘停止",
        "description": "採掘を停止します。すでに停止中なら何もしません。アプリ自体は終了しません。",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
    },
]


class ToolError(Exception):
    """A failure the model should see as the tool's result (isError), not a protocol error."""


def _base_url() -> str:
    url = os.environ.get("MONAMINER_URL", "").strip()
    if url:
        return url.rstrip("/")
    port = 8888
    try:
        cfg_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
        with open(cfg_path, "r", encoding="utf-8") as f:
            port = int(json.load(f).get("web_dashboard_port", port))
    except Exception:
        pass   # no config yet / unreadable: the default port
    return f"http://127.0.0.1:{port}"


def _http(method: str, path: str) -> dict:
    url = _base_url() + path
    req = urllib.request.Request(url, data=b"" if method == "POST" else None, method=method)
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as resp:
            return json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        raise ToolError(f"MonaMiner RTX が要求を拒否しました (HTTP {e.code}): {url}")
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise ToolError(
            f"MonaMiner RTX に接続できません ({url})。アプリが起動していて、"
            f"「遠隔監視・通知」タブの Web ダッシュボードが有効になっているか確認してください。詳細: {e}"
        )


def _status_without_logs() -> dict:
    status = _http("GET", "/api/status")
    status.pop("recent_logs", None)
    return status


def tool_get_status(args: dict) -> dict:
    return _status_without_logs()


def tool_get_logs(args: dict) -> dict:
    lines = args.get("lines", 30)
    if not isinstance(lines, int) or isinstance(lines, bool) or not 1 <= lines <= 200:
        raise ToolError("lines は 1 から 200 の整数で指定してください。")
    logs = _http("GET", "/api/status").get("recent_logs") or []
    return {"lines": logs[-lines:]}


def tool_start_mining(args: dict) -> dict:
    if _status_without_logs().get("is_mining"):
        return {"changed": False, "message": "すでに採掘中です。", "status": _status_without_logs()}
    _http("POST", "/api/start")
    return {"changed": True, "message": "採掘開始を要求しました。ハッシュレートが出るまで数秒かかります。",
            "status": _status_without_logs()}


def tool_stop_mining(args: dict) -> dict:
    if not _status_without_logs().get("is_mining"):
        return {"changed": False, "message": "すでに停止しています。", "status": _status_without_logs()}
    _http("POST", "/api/stop")
    return {"changed": True, "message": "採掘を停止しました。", "status": _status_without_logs()}


HANDLERS = {
    "get_status": tool_get_status,
    "get_logs": tool_get_logs,
    "start_mining": tool_start_mining,
    "stop_mining": tool_stop_mining,
}


def _result(req_id, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _error(req_id, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def handle(msg):
    """Returns the response for one JSON-RPC message, or None when none is due (notifications)."""
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
        return _error(msg.get("id") if isinstance(msg, dict) else None, -32600, "Invalid Request")
    method = msg.get("method")
    if method is None:
        return None                      # a response to something we never asked: ignore
    if "id" not in msg:
        return None                      # notification (notifications/initialized, cancelled, ...)
    req_id = msg["id"]
    params = msg.get("params") or {}

    if method == "initialize":
        wanted = params.get("protocolVersion")
        return _result(req_id, {
            "protocolVersion": wanted if wanted in SUPPORTED_PROTOCOLS else SUPPORTED_PROTOCOLS[0],
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "title": "MonaMiner RTX", "version": SERVER_VERSION},
            "instructions": (
                "MonaMiner RTX (Monacoin / Lyra2REv2 マイナー) の状態確認と採掘の開始・停止を行います。"
                "アプリ本体が起動している必要があります。"
            ),
        })
    if method == "ping":
        return _result(req_id, {})
    if method == "tools/list":
        return _result(req_id, {"tools": TOOLS})
    if method == "tools/call":
        name = params.get("name")
        handler = HANDLERS.get(name)
        if handler is None:
            return _error(req_id, -32602, f"Unknown tool: {name}")
        args = params.get("arguments") or {}
        if not isinstance(args, dict):
            return _error(req_id, -32602, "arguments must be an object")
        try:
            data = handler(args)
            text = json.dumps(data, ensure_ascii=False, indent=2)
            return _result(req_id, {"content": [{"type": "text", "text": text}], "isError": False})
        except ToolError as e:
            return _result(req_id, {"content": [{"type": "text", "text": str(e)}], "isError": True})
        except Exception as e:   # a bug here must not kill the session
            return _result(req_id, {"content": [{"type": "text", "text": f"内部エラー: {e!r}"}], "isError": True})
    return _error(req_id, -32601, f"Method not found: {method}")


def main():
    # stdio transport: one JSON message per line, UTF-8, "\n" only. Text mode on Windows would
    # write "\r\n" and use the ANSI code page, so both streams are used as raw bytes.
    stdin, stdout = sys.stdin.buffer, sys.stdout.buffer
    for raw in stdin:
        line = raw.strip()
        if not line:
            continue
        try:
            msg = json.loads(line.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            responses = [_error(None, -32700, "Parse error")]
        else:
            if isinstance(msg, list):   # JSON-RPC batch (allowed by the 2025-03-26 revision)
                responses = [r for r in (handle(m) for m in msg) if r is not None]
                responses = [responses] if responses else []
            else:
                r = handle(msg)
                responses = [r] if r is not None else []
        for r in responses:
            stdout.write(json.dumps(r, ensure_ascii=False).encode("utf-8") + b"\n")
            stdout.flush()


if __name__ == "__main__":
    main()
