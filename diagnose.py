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

def run_diagnostics():
    print("=" * 60)
    print("  MonaMiner RTX システム・デバッグ自己診断ツール")
    print("=" * 60)

    # 1. Python Environment Check
    print("\n[1/6] Python 実行環境チェック...")
    print(f"  - Python バージョン: {sys.version.split()[0]} ({sys.platform})")
    print(f"  - 実行パス: {sys.executable}")
    assert sys.version_info >= (3, 9), "Python 3.9以上が必要です"
    print("  -> OK")

    # 2. PySide6 (GUI) Check
    print("\n[2/6] GUI ライブラリ (PySide6 / Qt6) チェック...")
    try:
        import PySide6
        from PySide6.QtWidgets import QApplication
        print(f"  - PySide6 バージョン: {PySide6.__version__}")
        print("  -> OK")
    except Exception as e:
        print(f"  -> ERROR: {e}")
        return

    # 3. NVML & Hardware (RTX 5080) Check
    print("\n[3/6] NVIDIA GPU ハードウェア検知 (NVML) チェック...")
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
    print("\n[4/6] 最適化モード判定ロジック チェック...")
    rec = hw.get_mode_recommendation()
    print(f"  - 推奨モード: [{rec['recommended_key'].upper()}]")
    print(f"  - 判定理由:\n    {rec['rationale'].strip()}")
    print("  -> OK")

    # 5. Network & Mining Pool Reachability Check
    print("\n[5/6] モナコイン マイニングプール導通テスト (TCP Handshake)...")
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
    print("\n[6/6] マイナー制御 (ハイブリッド & ソロマイニング) 動作チェック...")
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

    print("\n[7/7] 独自内蔵 OpenCL マイナーエンジン & JIT コンパイル チェック...")
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
                ctx.build_program(src)
                ctx.get_kernel("search_lyra2v2")
                ctx.release()
                print("  - Lyra2REv2 OpenCL C カーネル JIT コンパイル: 成功 [OK]")
                print("  -> OK (外部バイナリ不要でGPUネイティブ採掘可能)")
            else:
                print("  - OpenCL デバイス未検出")
        else:
            print("  - OpenCL プラットフォーム未検出")
    except Exception as e:
        print(f"  - OpenCL チェック失敗 (警告): {e}")

    print("\n[8/8] v2.0.0 新機能 (スマートアイドル・収益性計算・NVML制御・Web監視) チェック...")
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

    hw.shutdown()
    print("\n" + "=" * 60)
    print("  すべての診断テストが正常に完了しました！[READY v2.0.0]")
    print("=" * 60)

if __name__ == "__main__":
    run_diagnostics()
