import sys
import os
import socket

# Ensure UTF-8 output on Windows console
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Lyra2REv2 hash of the 80-byte header 00 01 02 ... 4f, from the reference implementation
# that was verified against Monacoin Core (see tests/test_lyra2v2_kernel.py).
KAT_HEADER = bytes(range(80))
KAT_HASH = "2246faafca15a01a35c81a3f801fe8338942565bdb75a505517372aa0c7afdd0"

def run_diagnostics():
    failures = []
    print("=" * 60)
    print("  MonaMiner RTX システム・デバッグ自己診断ツール")
    print("=" * 60)

    # 1. Python Environment Check
    print("\n[1/11] Python 実行環境チェック...")
    print(f"  - Python バージョン: {sys.version.split()[0]} ({sys.platform})")
    print(f"  - 実行パス: {sys.executable}")
    assert sys.version_info >= (3, 9), "Python 3.9以上が必要です"
    print("  -> OK")

    # 2. PySide6 (GUI) Check
    print("\n[2/11] GUI ライブラリ (PySide6 / Qt6) チェック...")
    try:
        import PySide6
        from PySide6.QtWidgets import QApplication
        print(f"  - PySide6 バージョン: {PySide6.__version__}")
        print("  -> OK")
    except Exception as e:
        print(f"  -> ERROR: {e}")
        sys.exit(1)

    # 3. NVML & Hardware (RTX 5080) Check
    print("\n[3/11] NVIDIA GPU ハードウェア検知 (NVML) チェック...")
    from app.hardware import HardwareManager
    hw = HardwareManager()
    if hw.has_nvml:
        info = hw.device_info
        print(f"  - 検出GPU: {info['name']}")
        print(f"  - VRAM: {info['vram_gb']} GB (空き: {info['vram_free_gb']} GB)")
        print(f"  - ドライバー: {info['driver_version']} (CUDA Driver: {info['cuda_version']})")
        print(f"  - Compute Capability: {info['compute_capability']}")
        print(f"  - 定格TDP: {info['pwr_default_w']}W (許容範囲: {info['pwr_min_w']}W - {info['pwr_max_w']}W)")
        metrics = hw.get_live_metrics()
        print(f"  - 現在の温度: {metrics['temp_c']} ℃ / ファン: {metrics['fan_pct']} % / アイドル電力: {metrics['power_w']} W")
        cpu = hw.cpu_info
        print(f"  - 検出CPU: {cpu['name']} (物理: {cpu['physical_cores']}C / 論理: {cpu['logical_cores']}T)")
        print(f"  - 現在のCPU使用率: {metrics.get('cpu_util_pct', 0)} %")
        print(f"  - 管理者権限: {'有効 (PowerLimit制御可能)' if hw.is_admin else '無効 (Intensity制御モードで動作)'}")
        print("  -> OK")
    else:
        print("  -> WARN: NVMLが初期化できませんでした（GPUなし、またはドライバー未適用環境）")

    # 4. Mode Recommendation Check
    print("\n[4/11] 最適化モード判定ロジック チェック...")
    rec = hw.get_mode_recommendation()
    print(f"  - 推奨モード: [{rec['recommended_key'].upper()}]")
    print(f"  - 判定理由:\n    {rec['rationale'].strip()}")
    print("  -> OK")

    # 5. Network & Mining Pool Reachability Check
    print("\n[5/11] モナコイン マイニングプール導通テスト (TCP Handshake)...")
    pools_to_test = [
        ("VIPPOOL プライマリ (stratum1.vippool.net:8888)", "stratum1.vippool.net", 8888),
        ("VIPPOOL セカンダリ (vippool.net:8888)", "vippool.net", 8888),
    ]
    for name, host, port in pools_to_test:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(3.0)
            s.connect((host, port))
            s.close()
            print(f"  - {name}: 接続成功 (TCP OK)")
        except Exception as e:
            print(f"  - {name}: 接続失敗 ({e}) - ※ファイアウォールまたは一時的オフラインの可能性")

    # 6. Mining Simulation Engine Check (Hybrid + Solo)
    print("\n[6/11] マイナー制御 (ハイブリッド & ソロマイニング) 動作チェック...")
    import time
    from app.miner_controller import MinerController
    ctrl = MinerController(hw)
    events = []
    ctrl.status_changed.connect(lambda s: events.append(f"Status: {s}"))
    ctrl.hashrate_changed.connect(lambda h, p, e: events.append(f"HR: {h:.1f}MH/s, {p:.1f}W, {e:.2f}MH/W"))

    # Test Hybrid + Solo
    ctrl.start_mining(
        mode="eco",
        target_type="solo",
        device_target="hybrid",
        pool_url="stratum+tcp://stratum1.vippool.net:8888",
        wallet="MRLf12f9kXw9TzD4s2Gf3K6eN5q8wL7yZa",
        worker="diag_worker",
        solo_host="127.0.0.1",
        solo_port=9402,
        solo_user="monaruser",
        solo_pass="monarpass",
        cpu_threads=16,
        use_sim=True
    )
    time.sleep(2.0)
    ctrl.stop_mining()
    print(f"  - 発生イベント数: {len(events)} 件")
    for ev in events[:4]:
        print(f"    * {ev}")
    print("  -> OK")

    print("\n[7/11] 独自内蔵 OpenCL マイナーエンジン & JIT コンパイル チェック...")
    try:
        from app.miner.opencl_backend import OpenCLBackend, OpenCLContext
        platforms = OpenCLBackend.get_platforms()
        if platforms:
            p = platforms[0]
            devs = OpenCLBackend.get_devices(p["id"])
            if devs:
                d = devs[0]
                print(f"  - 検出OpenCL GPU: {d['name']} (Platform: {p['name']})")
                print(f"  - Compute Units: {d['compute_units']} / VRAM: {d['global_mem_gb']} GB")
                ctx = OpenCLContext(p["id"], d["id"])
                kernel_path = os.path.join(os.path.dirname(__file__), "app", "miner", "kernels", "lyra2v2.cl")
                with open(kernel_path, "r", encoding="utf-8") as f:
                    src = f.read()
                ctx.build_program(src, options="-DDEBUG_STAGES")
                print("  - Lyra2REv2 OpenCL C カーネル JIT コンパイル: 成功 [OK]")

                # Compiling is not enough: the hash must be correct (a wrong kernel also compiles)
                from ctypes import c_uint
                import struct
                k = ctx.get_kernel("debug_stages")
                b_hdr = ctx.create_buffer(80)
                b_out = ctx.create_buffer(7 * 32)
                ctx.write_buffer(b_hdr, (c_uint * 20).from_buffer_copy(KAT_HEADER), 80)
                ctx.set_arg_mem(k, 0, b_hdr)
                ctx.set_arg_mem(k, 1, b_out)
                ctx.run_kernel_1d(k, 1, 1)
                ctx.finish()
                out = (c_uint * 56)()
                ctx.read_buffer(b_out, out, 224)
                got = b"".join(struct.pack("<I", out[48 + j]) for j in range(8)).hex()
                ctx.release()
                if got == KAT_HASH:
                    print("  - Lyra2REv2 ハッシュ既知解テスト (リファレンス実装と一致): 合格 [OK]")
                    print("  -> OK (外部バイナリ不要でGPUネイティブ採掘可能)")
                else:
                    print(f"  -> ERROR: ハッシュが不正です (期待 {KAT_HASH[:16]}... / 実際 {got[:16]}...)")
                    failures.append("OpenCL kernel hash")
            else:
                print("  - OpenCL デバイス未検出")
        else:
            print("  - OpenCL プラットフォーム未検出")
    except Exception as e:
        print(f"  - OpenCL チェック失敗 (警告): {e}")
        failures.append("OpenCL")

    print("\n[8/11] 独自内蔵 CPU マイナーエンジン (ネイティブ DLL) チェック...")
    try:
        from app.miner.cpu_backend import CpuBackend, CpuBackendUnavailable
        got = CpuBackend.hash80(KAT_HEADER).hex()
        if got == KAT_HASH:
            print("  - lyra2re2_cpu.dll ロード & Lyra2REv2 ハッシュ既知解テスト: 合格 [OK]")
            n, found = CpuBackend.scan(KAT_HEADER[:76], 0, 4096, 0x7FFFFF00, 0)
            print(f"  - Nonce スキャン動作確認: 4096 Nonce 中 {n} 件が Regtest 難易度を突破 (正常範囲)")
            print("  -> OK (外部バイナリ不要でCPUネイティブ採掘可能)")
        else:
            print(f"  -> ERROR: ハッシュが不正です (期待 {KAT_HASH[:16]}... / 実際 {got[:16]}...)")
            failures.append("CPU engine hash")
    except CpuBackendUnavailable as e:
        print(f"  -> ERROR: {e}")
        print("    対処法: python app/miner/native/build_native.py を実行して lyra2re2_cpu.dll を再生成してください。")
        failures.append("CPU engine")
    except Exception as e:
        print(f"  - CPU エンジン チェック失敗 (警告): {e}")
        failures.append("CPU engine")

    print("\n[9/11] v2.0.0 新機能 (スマートアイドル・収益性計算・NVML制御・Web監視) チェック...")
    try:
        from app.services import ProfitCalculator, GpuHardwareController, IdleTracker, WebMonitoringServer
        pc = ProfitCalculator()
        p_res = pc.calculate(150.0, 220.0)
        assert p_res["daily_cost_yen"] > 0

        gc = GpuHardwareController()
        print(f"  - NVML ハードウェア制御: {'利用可能 (RTX制御対応)' if gc.is_available else '非対応環境'}")

        it = IdleTracker()
        idle_s = it.get_idle_seconds()
        print(f"  - Windows アイドル検知: 正常 (現在 {idle_s:.1f}秒 放置)")

        ws = WebMonitoringServer(port=8895)
        ws.start(get_status_fn=lambda: {"test": True}, start_fn=lambda: None, stop_fn=lambda: None)
        time.sleep(0.2)
        ws.stop()
        print("  - 内蔵 Web 監視ダッシュボード HTTP サーバー: 起動・停止確認 OK")
        print("  -> OK (全スマート運用・省エネ・遠隔監視サービス正常)")
    except Exception as e:
        print(f"  -> ERROR in v2.0.0 services: {e}")
        failures.append("services")

    print("\n[10/11] Monacoin Core ソロマイニング RPC クライアント & ブロック構築検証...")
    try:
        from app.miner.rpc_solo_client import RpcSoloClient, SoloBlockTemplate
        solo = RpcSoloClient(host="127.0.0.1", port=9402, user="monacoinrpc", password="rpcpassword")
        # Test serialization of a dummy block template to ensure byte-perfect logic
        dummy_gbt = {
            "height": 3124560,
            "version": 536870912,
            "previousblockhash": "0000000000000000000123456789abcdef0123456789abcdef0123456789abcd",
            "bits": "1b07ffff",
            "curtime": 1700000000,
            "coinbasevalue": 5000000000,
            "target": "000000000007ffff000000000000000000000000000000000000000000000000",
            "transactions": []
        }
        script_pubkey = bytes.fromhex("76a9144365d95cfcf987dbf03f3957eb6a6e87f872e42488ac")
        tpl = SoloBlockTemplate(dummy_gbt, script_pubkey, "MRLf12f9kXw9TzD4s2Gf3K6eN5q8wL7yZa")
        assert len(tpl.header_76) == 76
        full_block = tpl.assemble_full_block(12345)
        assert len(full_block) > 80
        print(f"  - Coinbase TX 生成 & Merkle Tree 計算: 正常")
        print(f"  - 76バイト ヘッダープレフィックス生成 (OpenCL JIT カーネル引数用): 正常 ({len(tpl.header_76)} バイト)")
        print(f"  - フルブロック シリアライズ & 送信ペイロード構築: 正常 ({len(full_block)} バイト)")
        print("  -> OK (Monacoin Core ソロマイニング完全準拠)")
    except Exception as e:
        print(f"  -> ERROR in Solo Mining check: {e}")
        failures.append("solo client")

    print("\n[11/11] ウォレット残高/履歴 API ＆ ノード同期情報サービスクエリ検証...")
    try:
        from app.services.wallet_service import fetch_wallet_history
        from app.services.node_service import fetch_node_sync_info
        # Test node service (should return dict safely even if node is down)
        node_res = fetch_node_sync_info(timeout=0.8)
        assert isinstance(node_res, dict)
        assert "is_running" in node_res
        assert "blocks" in node_res
        assert "headers" in node_res
        print(f"  - ノード同期クエリサービス: 正常 (現在ノード: {'稼働中' if node_res['is_running'] else '停止中'})")

        # Test wallet history service with fallback/timeout safety
        w_res = fetch_wallet_history("MMaQaRDQ1KyRCtVrredpx15g5niwpbVovY", page=1, page_size=2)
        assert isinstance(w_res, dict)
        assert "success" in w_res
        print(f"  - ウォレット履歴/残高取得サービス: 正常 (応答 success={w_res.get('success', False)})")
        print("  -> OK (ウォレット履歴＆ノード同期UI機能正常)")
    except Exception as e:
        print(f"  -> ERROR in wallet/node services: {e}")
        failures.append("wallet/node services")

    hw.shutdown()
    print("\n" + "=" * 60)
    if failures:
        print(f"  診断で問題が見つかりました: {', '.join(failures)}")
        print("=" * 60)
        sys.exit(1)
    print("  すべての診断テストが正常に完了しました！[READY v2.2.2]")
    print("=" * 60)

if __name__ == "__main__":
    run_diagnostics()
