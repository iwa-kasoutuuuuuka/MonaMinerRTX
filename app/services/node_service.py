"""
Node Sync Status Service for Monacoin Core
Provides fast, non-blocking queries for local Monacoin Core blockchain sync info.
"""
import base64
import json
import urllib.request
import urllib.error
from typing import Dict, Any


def fetch_node_sync_info(host: str = "127.0.0.1", port: int = 9402,
                         user: str = "monacoinrpc", password: str = "rpcpassword",
                         timeout: float = 1.5) -> Dict[str, Any]:
    """
    ローカルの Monacoin Core ノードに getblockchaininfo を問い合わせ、
    現在のブロック高（ローカル所持ブロック）とネットワーク最新ブロック高（headers）を取得します。
    """
    ports_to_try = [port]
    if port != 19402:
        ports_to_try.append(19402)  # Regtest default port check

    for p in ports_to_try:
        url = f"http://{host}:{p}/"
        payload = json.dumps({
            "jsonrpc": "1.0",
            "id": "status_check",
            "method": "getblockchaininfo",
            "params": []
        }).encode("utf-8")

        auth_str = f"{user}:{password}"
        auth_header = f"Basic {base64.b64encode(auth_str.encode('utf-8')).decode('utf-8')}"

        req = urllib.request.Request(
            url,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": auth_header
            }
        )

        try:
            with urllib.request.urlopen(req, timeout=timeout) as res:
                body = res.read().decode("utf-8")
                resp = json.loads(body)

                if resp.get("error"):
                    # Check for loading block index error (-28)
                    err = resp["error"]
                    err_msg = err.get("message", "RPCエラー")
                    return {
                        "is_running": True,
                        "is_loading": True,
                        "chain": "main",
                        "blocks": 0,
                        "headers": 0,
                        "progress": 0.0,
                        "ibd": True,
                        "status_text": f"ノード起動・初期化中... ({err_msg})",
                        "port": p
                    }

                info = resp.get("result", {})
                chain = info.get("chain", "unknown")
                blocks = int(info.get("blocks", 0))
                headers = int(info.get("headers", 0))
                ibd = bool(info.get("initialblockdownload", False))
                diff = float(info.get("difficulty", 0.0))
                verif_prog = float(info.get("verificationprogress", 0.0))

                # 進捗率の計算 (headersベース、またはverificationprogressベース)
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

                return {
                    "is_running": True,
                    "is_loading": False,
                    "chain": chain,
                    "blocks": blocks,
                    "headers": headers,
                    "progress": prog_percent,
                    "ibd": ibd,
                    "difficulty": diff,
                    "status_text": status_text,
                    "port": p
                }

        except urllib.error.HTTPError as e:
            # -28: Loading block index, etc.
            try:
                err_data = json.loads(e.read().decode("utf-8"))
                err_msg = err_data.get("error", {}).get("message", "")
                if "loading" in err_msg.lower() or "block index" in err_msg.lower():
                    return {
                        "is_running": True,
                        "is_loading": True,
                        "chain": "main",
                        "blocks": 0,
                        "headers": 0,
                        "progress": 0.0,
                        "ibd": True,
                        "status_text": f"ノード起動中: {err_msg}",
                        "port": p
                    }
            except Exception:
                pass
            continue
        except Exception:
            continue

    # すべてのポートで応答なし
    return {
        "is_running": False,
        "is_loading": False,
        "chain": "none",
        "blocks": 0,
        "headers": 0,
        "progress": 0.0,
        "ibd": False,
        "difficulty": 0.0,
        "status_text": "ノード停止中 (ローカルノード未起動)",
        "port": port
    }
