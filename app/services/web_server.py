"""
Lightweight embedded Web Monitoring Dashboard & REST API.
Built using Python's standard http.server.ThreadingHTTPServer.
Zero third-party web frameworks needed (keeps portable binary tiny).
"""
import json
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Callable, Dict, Any, Optional

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>MonaMinerRTX Web Dashboard</title>
    <style>
        :root {
            --bg-color: #0d1117;
            --card-bg: #161b22;
            --border-color: #30363d;
            --accent-green: #2ea043;
            --accent-cyan: #58a6ff;
            --accent-red: #da3633;
            --text-main: #c9d1d9;
            --text-bold: #f0f6fc;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
        body { background-color: var(--bg-color); color: var(--text-main); padding: 16px; display: flex; flex-direction: column; align-items: center; }
        .container { max-width: 800px; width: 100%; }
        header { display: flex; justify-content: space-between; align-items: center; padding-bottom: 16px; border-bottom: 1px solid var(--border-color); margin-bottom: 20px; }
        h1 { font-size: 1.4rem; color: var(--text-bold); display: flex; align-items: center; gap: 8px; }
        .badge { background: #238636; color: white; padding: 4px 10px; border-radius: 12px; font-size: 0.8rem; font-weight: bold; }
        .badge.stopped { background: #6e7681; }
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 14px; margin-bottom: 20px; }
        .card { background: var(--card-bg); border: 1px solid var(--border-color); border-radius: 8px; padding: 16px; }
        .card-label { font-size: 0.8rem; color: #8b949e; margin-bottom: 6px; }
        .card-val { font-size: 1.6rem; font-weight: bold; color: var(--text-bold); }
        .card-val.green { color: var(--accent-green); }
        .card-val.cyan { color: var(--accent-cyan); }
        .actions { display: flex; gap: 12px; margin-bottom: 20px; }
        button { flex: 1; padding: 12px; border: none; border-radius: 6px; font-size: 1rem; font-weight: bold; cursor: pointer; transition: 0.2s; }
        .btn-start { background: var(--accent-green); color: white; }
        .btn-stop { background: var(--accent-red); color: white; }
        button:hover { opacity: 0.85; }
        button:disabled { opacity: 0.4; cursor: not-allowed; }
        .log-box { background: #010409; border: 1px solid var(--border-color); border-radius: 6px; padding: 12px; font-family: monospace; font-size: 0.85rem; height: 180px; overflow-y: auto; color: #7ee787; white-space: pre-wrap; }
    </style>
</head>
<body>
<div class="container">
    <header>
        <h1>⚡ MonaMinerRTX <span style="font-size: 0.9rem; color: #8b949e;">v2.0.0</span></h1>
        <span id="miner-status" class="badge">確認中...</span>
    </header>

    <div class="grid">
        <div class="card">
            <div class="card-label">総ハッシュレート</div>
            <div id="val-hashrate" class="card-val cyan">0.0 MH/s</div>
        </div>
        <div class="card">
            <div class="card-label">GPU温度 / ファン</div>
            <div id="val-temp" class="card-val">--℃ / --%</div>
        </div>
        <div class="card">
            <div class="card-label">消費電力 / 電力効率</div>
            <div id="val-power" class="card-val">-- W (-- W/MH)</div>
        </div>
        <div class="card">
            <div class="card-label">シェア (承認 / 拒否)</div>
            <div id="val-shares" class="card-val green">0 / 0</div>
        </div>
        <div class="card">
            <div class="card-label">電気代 (1日 / 1時間)</div>
            <div id="val-cost" class="card-val">¥-- / ¥--</div>
        </div>
        <div class="card">
            <div class="card-label">稼働時間</div>
            <div id="val-uptime" class="card-val">00:00:00</div>
        </div>
    </div>

    <div class="actions">
        <button id="btn-start" class="btn-start" onclick="remoteAction('start')">▶ 遠隔マイニング開始</button>
        <button id="btn-stop" class="btn-stop" onclick="remoteAction('stop')">⏹ 遠隔マイニング停止</button>
    </div>

    <div class="card-label" style="margin-bottom: 6px;">📋 最新マイニングログ</div>
    <div id="log-box" class="log-box">ログ待機中...</div>
</div>

<script>
    async function updateStatus() {
        try {
            const res = await fetch('/api/status');
            const data = await res.json();
            
            const badge = document.getElementById('miner-status');
            if (data.is_mining) {
                badge.innerText = '● 稼働中 (Mining)';
                badge.className = 'badge';
                document.getElementById('btn-start').disabled = true;
                document.getElementById('btn-stop').disabled = false;
            } else {
                badge.innerText = '○ 停止中 (Stopped)';
                badge.className = 'badge stopped';
                document.getElementById('btn-start').disabled = false;
                document.getElementById('btn-stop').disabled = true;
            }

            document.getElementById('val-hashrate').innerText = data.hashrate_mhs.toFixed(2) + ' MH/s';
            document.getElementById('val-temp').innerText = (data.temp_c || '--') + '℃ / ' + (data.fan_percent || '--') + '%';
            document.getElementById('val-power').innerText = (data.power_w || '--') + ' W (' + (data.watt_per_mh ? data.watt_per_mh.toFixed(3) : '--') + ' W/MH)';
            document.getElementById('val-shares').innerText = data.accepted_shares + ' / ' + data.rejected_shares;
            document.getElementById('val-cost').innerText = '¥' + (data.daily_cost_yen || 0) + ' / ¥' + (data.hourly_cost_yen || 0);
            document.getElementById('val-uptime').innerText = data.uptime_str || '00:00:00';
            
            if (data.recent_logs && data.recent_logs.length > 0) {
                const box = document.getElementById('log-box');
                box.innerText = data.recent_logs.join('\\n');
                box.scrollTop = box.scrollHeight;
            }
        } catch(e) {
            console.error(e);
        }
    }

    async function remoteAction(action) {
        if (!confirm('マイニングを ' + (action === 'start' ? '開始' : '停止') + ' しますか？')) return;
        try {
            await fetch('/api/' + action, { method: 'POST' });
            setTimeout(updateStatus, 500);
        } catch(e) {
            alert('操作エラー: ' + e);
        }
    }

    setInterval(updateStatus, 3000);
    updateStatus();
</script>
</body>
</html>
"""


class WebServerRequestHandler(BaseHTTPRequestHandler):
    get_status_callback: Optional[Callable[[], Dict[str, Any]]] = None
    start_callback: Optional[Callable[[], None]] = None
    stop_callback: Optional[Callable[[], None]] = None

    def log_message(self, format, *args):
        # Suppress noisy standard HTTP access logs
        return

    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML_TEMPLATE.encode("utf-8"))
        elif self.path == "/api/status":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            status = {}
            cb = WebServerRequestHandler.get_status_callback
            if cb:
                status = cb()
            self.wfile.write(json.dumps(status).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == "/api/start":
            cb = WebServerRequestHandler.start_callback
            if cb:
                cb()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"success": True}).encode("utf-8"))
        elif self.path == "/api/stop":
            cb = WebServerRequestHandler.stop_callback
            if cb:
                cb()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"success": True}).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()


class WebMonitoringServer:
    def __init__(self, host: str = "0.0.0.0", port: int = 8888):
        self.host = host
        self.port = port
        self.server: Optional[HTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self.is_running = False

    def start(self, get_status_fn, start_fn, stop_fn):
        if self.is_running:
            return

        WebServerRequestHandler.get_status_callback = get_status_fn
        WebServerRequestHandler.start_callback = start_fn
        WebServerRequestHandler.stop_callback = stop_fn

        try:
            self.server = HTTPServer((self.host, self.port), WebServerRequestHandler)
            self.is_running = True
            self._thread = threading.Thread(target=self.server.serve_forever, daemon=True)
            self._thread.start()
        except Exception as e:
            self.is_running = False
            raise e

    def stop(self):
        if self.server:
            try:
                self.server.shutdown()
                self.server.server_close()
            except Exception:
                pass
            self.is_running = False
            self.server = None
