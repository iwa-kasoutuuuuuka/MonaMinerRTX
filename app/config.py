import os
import json
import re

CONFIG_FILE_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.json")

DEFAULT_POOLS = [
    {
        "name": "VIPPOOL (国内最大・稼働中代表プール)",
        "url": "stratum+tcp://stratum1.vippool.net:8888",
        "doc": "https://vippool.net"
    },
    {
        "name": "VIPPOOL 予備 (vippool.net:8888)",
        "url": "stratum+tcp://vippool.net:8888",
        "doc": "https://vippool.net"
    },
    {
        "name": "カスタム (手動入力)",
        "url": "",
        "doc": ""
    }
]

# Monacoin address regex
# Legacy P2PKH starts with 'M' (33-34 chars)
# SegWit Bech32 starts with 'mona1' (usually 42 chars)
BASE58_REGEX = re.compile(r"^M[1-9A-HJ-NP-Za-km-z]{32,34}$")
BECH32_REGEX = re.compile(r"^mona1[qpzry9x8gf2tvdw0s3jn54khce6mua7l]{38,62}$")

def validate_mona_address(address: str) -> tuple[bool, str]:
    if not address or not address.strip():
        return False, "アドレスが入力されていません"
    addr = address.strip()
    if addr.startswith("M"):
        if BASE58_REGEX.match(addr):
            return True, "有効なレガシーアドレス (P2PKH) です"
        else:
            return False, "不正なレガシーアドレス形式です (文字数または使用禁止文字)"
    elif addr.startswith("mona1"):
        if BECH32_REGEX.match(addr):
            return True, "有効なSegWitアドレス (Bech32) です"
        else:
            return False, "不正なSegWitアドレス形式です"
    else:
        return False, "モナコインアドレスは 'M' または 'mona1' で始まる必要があります"

class ConfigManager:
    def __init__(self, filepath=CONFIG_FILE_PATH):
        self.filepath = filepath
        self.data = {
            "wallet_address": "MRLf12f9kXw9TzD4s2Gf3K6eN5q8wL7yZa", # Sample placeholder
            "mining_target": "pool", # 'pool' or 'solo'
            "pool_index": 0,
            "custom_pool_url": "",
            "worker_name": "rtx5080_worker",
            "pool_password": "x",
            "solo_host": "127.0.0.1",
            "solo_port": 9402,
            "solo_user": "monacoinrpc",
            "solo_pass": "rpcpassword",
            "device_target": "gpu", # 'gpu', 'cpu', 'hybrid'
            "cpu_threads": 16,
            "miner_mode": "auto",  # auto, eco, perf, quiet
            "custom_miner_path": "",
            "custom_cpuminer_path": "",
            "use_simulator": True, # Default to test/simulation mode
            "auto_start_mining": False,
            # v2.0.0 New Features
            "idle_mining_enabled": False,
            "idle_mining_minutes": 5,
            "electricity_rate_yen": 31.0,
            "mona_jpy_price": 45.0,
            "discord_webhook_url": "",
            "discord_notify_events": True,
            "web_dashboard_enabled": True,
            "web_dashboard_port": 8888,
            "multi_gpu_enabled": False,
            "selected_gpu_indices": [0],
            "power_limit_watts": 0,
            "target_fan_percent": 0
        }
        self.load()

    def load(self):
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                    self.data.update(loaded)
            except Exception as e:
                print(f"[Config] Error loading config: {e}")

    def save(self):
        try:
            with open(self.filepath, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[Config] Error saving config: {e}")

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value
        self.save()
