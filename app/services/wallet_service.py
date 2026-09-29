"""
Wallet Information and Transaction History Service for Monacoin
Supports fetching real-time balance and transaction history via Blockbook/Insight APIs.
"""
import json
import datetime
import urllib.request
import urllib.error
from typing import Dict, Any, List

BLOCKBOOK_API = "https://blockbook.electrum-mona.org/api/v2/address"
INSIGHT_API = "https://insight.electrum-mona.org/api"


def fetch_wallet_history(address: str, page: int = 1, page_size: int = 50) -> Dict[str, Any]:
    """
    指定されたモナコインアドレスの残高および入出金履歴を取得します。
    """
    clean_addr = address.strip()
    if not clean_addr:
        return {
            "success": False,
            "error": "アドレスが入力されていません。",
            "address": "",
            "balance": 0.0,
            "total_received": 0.0,
            "total_sent": 0.0,
            "tx_count": 0,
            "transactions": []
        }

    sat = 100000000.0

    # 1. Blockbook API (Primary)
    try:
        url = f"{BLOCKBOOK_API}/{clean_addr}?details=txs&pageSize={page_size}&page={page}"
        req = urllib.request.Request(url, headers={"User-Agent": "MonaMinerRTX/2.1.0"})
        with urllib.request.urlopen(req, timeout=8) as res:
            data = json.loads(res.read().decode("utf-8"))

        balance = int(data.get("balance", 0)) / sat
        total_received = int(data.get("totalReceived", 0)) / sat
        total_sent = int(data.get("totalSent", 0)) / sat
        tx_count = int(data.get("txs", 0))
        total_pages = int(data.get("totalPages", 1))

        tx_list: List[Dict[str, Any]] = []
        for tx in data.get("transactions", []):
            txid = tx.get("txid", "")
            btime = tx.get("blockTime")
            if btime:
                try:
                    dt_str = datetime.datetime.fromtimestamp(btime).strftime("%Y-%m-%d %H:%M:%S")
                except Exception:
                    dt_str = str(btime)
            else:
                dt_str = "未承認 (Mempool)"

            confs = int(tx.get("confirmations", 0))

            # このアドレスに対する純変動（入金 - 出金）を算出
            received_sat = 0
            for out in tx.get("vout", []):
                if clean_addr in out.get("addresses", []):
                    received_sat += int(out.get("value", 0))

            sent_sat = 0
            for inp in tx.get("vin", []):
                if clean_addr in inp.get("addresses", []):
                    sent_sat += int(inp.get("value", 0))

            delta = (received_sat - sent_sat) / sat
            is_receive = delta >= 0

            tx_list.append({
                "txid": txid,
                "time": dt_str,
                "delta": delta,
                "is_receive": is_receive,
                "confirmations": confs,
                "fee": int(tx.get("fees", 0)) / sat,
                "block_height": tx.get("blockHeight", 0)
            })

        return {
            "success": True,
            "address": clean_addr,
            "balance": balance,
            "total_received": total_received,
            "total_sent": total_sent,
            "tx_count": tx_count,
            "page": page,
            "total_pages": total_pages,
            "transactions": tx_list,
            "explorer_url": f"https://blockbook.electrum-mona.org/address/{clean_addr}"
        }

    except Exception as e_bb:
        # Fallback to insight API
        try:
            url_in = f"{INSIGHT_API}/addr/{clean_addr}"
            req_in = urllib.request.Request(url_in, headers={"User-Agent": "MonaMinerRTX/2.1.0"})
            with urllib.request.urlopen(req_in, timeout=8) as res:
                data_in = json.loads(res.read().decode("utf-8"))

            balance = float(data_in.get("balance", 0.0))
            total_received = float(data_in.get("totalReceived", 0.0))
            total_sent = float(data_in.get("totalSent", 0.0))
            tx_count = int(data_in.get("txApperances", len(data_in.get("transactions", []))))

            # In insight addr, tx list is just hashes, so transactions list is summary
            tx_list = []
            for txid in data_in.get("transactions", [])[:page_size]:
                tx_list.append({
                    "txid": txid,
                    "time": "--",
                    "delta": 0.0,
                    "is_receive": True,
                    "confirmations": 1,
                    "fee": 0.0,
                    "block_height": 0
                })

            return {
                "success": True,
                "address": clean_addr,
                "balance": balance,
                "total_received": total_received,
                "total_sent": total_sent,
                "tx_count": tx_count,
                "page": 1,
                "total_pages": 1,
                "transactions": tx_list,
                "explorer_url": f"https://mona.chainsight.info/address/{clean_addr}"
            }
        except Exception as e_in:
            return {
                "success": False,
                "error": f"ウォレット情報の取得に失敗しました: {str(e_bb)}",
                "address": clean_addr,
                "balance": 0.0,
                "total_received": 0.0,
                "total_sent": 0.0,
                "tx_count": 0,
                "transactions": []
            }
