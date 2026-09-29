"""
Automated Regtest Solo Mining Environment Orchestrator.
Launches a dual-node Monacoin Core Regtest cluster on ports 9402 and 9403,
initializes the wallet, generates genesis/initial blocks to satisfy IBD rules,
and provides live RPC services for instant GPU solo mining.
"""

import os
import sys
import time
import json
import base64
import signal
import subprocess
import urllib.request
import urllib.error

def rpc(port: int, method: str, params: list = None, timeout: float = 5.0, wallet: str = None):
    if params is None:
        params = []
    payload = json.dumps({
        "jsonrpc": "1.0",
        "id": f"regtest_{method}",
        "method": method,
        "params": params
    }).encode("utf-8")
    auth = base64.b64encode(b"monacoinrpc:rpcpassword").decode("ascii")
    # With more than one wallet loaded, wallet RPCs must address a wallet explicitly.
    path = f"wallet/{wallet}" if wallet else ""
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/{path}",
        data=payload,
        headers={"Authorization": f"Basic {auth}", "Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))

def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    bin_path = os.path.join(base_dir, "bin", "monacoind.exe")
    
    if not os.path.exists(bin_path):
        print(f"[エラー] Monacoin Core バイナリが見つかりません: {bin_path}")
        sys.exit(1)
        
    dir_n1 = os.path.join(base_dir, "regtest_data", "n1")
    dir_n2 = os.path.join(base_dir, "regtest_data", "n2")
    os.makedirs(dir_n1, exist_ok=True)
    os.makedirs(dir_n2, exist_ok=True)

    print("==================================================================")
    print("  MonaMinerRTX - 即時テスト用 Regtest ソロマイニング環境 起動")
    print("==================================================================")
    print(f"・Primary Node (採掘ターゲット): RPC 127.0.0.1:9402 / P2P :20444")
    print(f"・Secondary Node (相互同期ピア): RPC 127.0.0.1:9403 / P2P :20445")
    print("------------------------------------------------------------------")

    # Start primary node
    cmd1 = [
        bin_path,
        f"-datadir={dir_n1}",
        "-regtest",
        "-server=1",
        "-rpcuser=monacoinrpc",
        "-rpcpassword=rpcpassword",
        "-rpcport=9402",
        "-port=20444",
        "-fallbackfee=0.0001",
        "-listen=1"
    ]
    p1 = subprocess.Popen(cmd1)

    # Start secondary node
    cmd2 = [
        bin_path,
        f"-datadir={dir_n2}",
        "-regtest",
        "-server=1",
        "-rpcuser=monacoinrpc",
        "-rpcpassword=rpcpassword",
        "-rpcport=9403",
        "-port=20445",
        "-addnode=127.0.0.1:20444",
        "-fallbackfee=0.0001"
    ]
    p2 = subprocess.Popen(cmd2)

    def shutdown(*args):
        print("\n[情報] Regtest ノード停止シグナル受信。ノードを安全にシャットダウンしています...")
        for port in [9402, 9403]:
            try:
                rpc(port, "stop")
            except Exception:
                pass
        p1.wait(5)
        p2.wait(5)
        print("[完了] ノードを停止しました。")
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    # Wait for RPC to respond
    print("[1/3] ノード起動待機中...")
    node_ready = False
    for _ in range(20):
        try:
            info = rpc(9402, "getblockchaininfo")
            if "result" in info:
                node_ready = True
                break
        except Exception:
            time.sleep(0.5)

    if not node_ready:
        print("[エラー] Primary Node の RPC 応答がありませんでした。")
        shutdown()
        return

    # Check/Create wallet
    print("[2/3] テスト用ウォレットの初期化...")
    try:
        wallets = rpc(9402, "listwallets").get("result", [])
        if "regtest_miner" not in wallets:
            try:
                rpc(9402, "createwallet", ["regtest_miner"])
            except Exception:
                # already exists on disk (second launch) -> just load it
                rpc(9402, "loadwallet", ["regtest_miner"])
    except Exception as e:
        print(f"  -> ウォレット初期化スキップ ({e})")

    # Ensure peers connected and exit IBD
    print("[3/3] ピア接続の確立とIBD(初期ブロックダウンロード)の解除...")
    for _ in range(15):
        try:
            net = rpc(9402, "getnetworkinfo")
            if net.get("result", {}).get("connections", 0) >= 1:
                break
        except Exception:
            pass
        time.sleep(0.5)

    # Reward address for the GUI ("受取アドレス"): mainnet addresses are invalid on a regtest node.
    reward_address = None
    try:
        reward_address = rpc(9402, "getnewaddress", wallet="regtest_miner").get("result")
    except Exception as e:
        print(f"  -> 受取アドレスの取得に失敗しました ({e})")

    # Monacoin's regtest checks PoW with scrypt below height 60 and with Lyra2REv2 from height 60 on.
    # The GPU miner implements Lyra2REv2 only, so let the node mine (cheaply) past that point first.
    lyra2_min_height = 61
    try:
        info = rpc(9402, "getblockchaininfo")["result"]
        if info["blocks"] < lyra2_min_height:
            rpc(9402, "generatetoaddress", [lyra2_min_height - info["blocks"], reward_address], timeout=120.0)
            print(f"  -> ブロック高 #{lyra2_min_height} まで初期ブロックを生成しました (Lyra2REv2 区間)。")
    except Exception as e:
        print(f"  -> 初期ブロック生成スキップ ({e})")

    # Confirm getblocktemplate is functioning
    try:
        gbt = rpc(9402, "getblocktemplate", [{"rules": ["segwit"]}])
        if "result" in gbt:
            height = gbt["result"]["height"]
            print(f"✓ 準備完了！ getblocktemplate 正常応答 (ブロック高: #{height})")
            print("==================================================================")
            print("  GPU ソロマイニング待機状態に入りました！")
            print("  MonaMinerRTX GUI の「ソロマイニング」タブで「採掘開始」を押すと、")
            print("  RTX 5080 等のGPUで直接ブロック採掘・即座承認を体験できます。")
            if reward_address:
                print()
                print("  ★ MonaMinerRTX の「モナコイン受取アドレス」には、このRegtest用アドレスを入力してください:")
                print(f"      {reward_address}")
                print("    (メインネット用の M... アドレスは Regtest ノードでは無効です)")
                print()
            print("  終了するには Ctrl+C を押してください。")
            print("==================================================================")
    except Exception as e:
        print(f"[警告] getblocktemplate の応答確認中に例外が発生しました: {e}")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        shutdown()

if __name__ == "__main__":
    main()
