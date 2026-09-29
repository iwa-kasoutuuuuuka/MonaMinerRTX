"""
Node Sync Status Service for Monacoin Core
Provides fast, non-blocking queries for local Monacoin Core blockchain sync info.
"""
import base64
import json
import urllib.request
import urllib.error
from typing import Dict, Any


def _status(port: int, **fields) -> Dict[str, Any]:
    info = {
        "is_running": False,
        "is_loading": False,
        "auth_error": False,
        "chain": "none",
        "blocks": 0,
        "headers": 0,
        "progress": 0.0,
        "ibd": False,
        "difficulty": 0.0,
        "status_text": "",
        "port": port,
    }
    info.update(fields)
    return info


def fetch_node_sync_info(host: str = "127.0.0.1", port: int = 9402,
                         user: str = "monacoinrpc", password: str = "rpcpassword",
                         timeout: float = 1.5) -> Dict[str, Any]:
    """
    ローカルの Monacoin Core ノードに getblockchaininfo を問い合わせ、
    現在のブロック高（ローカル所持ブロック）とネットワーク最新ブロック高（headers）を取得します。
    同梱の本番ノード・Regtest 環境はどちらも RPC ポート 9402 を使います。
    """
    payload = json.dumps({
        "jsonrpc": "1.0",
        "id": "status_check",
        "method": "getblockchaininfo",
        "params": []
    }).encode("utf-8")
    auth = base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii")
    req = urllib.request.Request(
        f"http://{host}:{port}/",
        data=payload,
        headers={"Content-Type": "application/json", "Authorization": f"Basic {auth}"}
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            resp = json.loads(res.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            return _status(port, is_running=True, auth_error=True,
                           status_text="RPC 認証エラー (ユーザー名/パスワードが一致しません)")
        # Monacoin Core answers HTTP 500 with a JSON error, e.g. -28 "Loading block index..."
        try:
            err_msg = json.loads(e.read().decode("utf-8")).get("error", {}).get("message", "")
        except Exception:
            err_msg = ""
        return _status(port, is_running=True, is_loading=True, ibd=True,
                       status_text=f"ノード起動・初期化中... ({err_msg or f'HTTP {e.code}'})")
    except Exception:
        return _status(port, status_text="ノード停止中 (ローカルノード未起動)")

    if resp.get("error"):
        err_msg = resp["error"].get("message", "RPCエラー")
        return _status(port, is_running=True, is_loading=True, ibd=True,
                       status_text=f"ノード起動・初期化中... ({err_msg})")

    info = resp.get("result") or {}
    blocks = int(info.get("blocks", 0))
    headers = int(info.get("headers", 0))
    ibd = bool(info.get("initialblockdownload", False))
    diff = float(info.get("difficulty", 0.0))
    verif_prog = float(info.get("verificationprogress", 0.0))

    if headers > 0:
        prog_percent = min(100.0, max(0.0, (blocks / headers) * 100.0))
    elif verif_prog > 0:
        prog_percent = min(100.0, verif_prog * 100.0)
    else:
        prog_percent = 100.0 if not ibd and blocks > 0 else 0.0

    if ibd:
        status_text = f"同期検証中 (IBD) : {blocks:,} / {headers:,} ブロック ({prog_percent:.1f}%)"
    else:
        status_text = f"同期完了・ソロ採掘可能 : 最新ブロック #{blocks:,} (Diff: {diff:,.1f})"

    return _status(port, is_running=True, chain=info.get("chain", "unknown"), blocks=blocks,
                   headers=headers, progress=prog_percent, ibd=ibd, difficulty=diff,
                   status_text=status_text)
