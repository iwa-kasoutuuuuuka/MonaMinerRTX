import sys
import os
import re
import time
import random
import subprocess
from PySide6.QtCore import QObject, Signal, QThread

class SimulatorWorker(QThread):
    """
    Simulates mining behavior for testing and UI responsiveness,
    accurately modeling RTX 5080 and CPU (Ryzen) under Pool or Solo mining.
    """
    hashrate_update = Signal(float, float, float) # hashrate_mhs, power_w, eff_mhw
    shares_update = Signal(int, int) # accepted/blocks, rejected
    log_message = Signal(str, str) # text, level

    def __init__(self, mode: str, target_type: str, device_target: str,
                 pool_url: str, wallet: str, worker: str,
                 solo_host: str, solo_port: int, solo_user: str, solo_pass: str,
                 cpu_threads: int, hardware_mgr):
        super().__init__()
        self.mode = mode
        self.target_type = target_type # "pool" or "solo"
        self.device_target = device_target # "gpu", "cpu", "hybrid"
        self.pool_url = pool_url
        self.wallet = wallet
        self.worker = worker
        self.solo_host = solo_host
        self.solo_port = solo_port
        self.solo_user = solo_user
        self.solo_pass = solo_pass
        self.cpu_threads = cpu_threads
        self.hardware_mgr = hardware_mgr
        self._running = True
        self.accepted_shares = 0
        self.rejected_shares = 0
        self.blocks_found = 0

    def run(self):
        dev_desc = {
            "gpu": "GPU (RTX 5080)",
            "cpu": f"CPU ({self.cpu_threads} Threads)",
            "hybrid": f"ハイブリッド (RTX 5080 + CPU {self.cpu_threads} Threads)"
        }.get(self.device_target, "GPU")

        self.log_message.emit(f"★ 採掘エンジン起動: Lyra2REv2 (MonaCoin)", "info")
        self.log_message.emit(f"使用デバイス: [{dev_desc}]", "info")
        self.log_message.emit(f"採掘モード: [{'ソロマイニング (Solo)' if self.target_type == 'solo' else 'プールマイニング (Pool)'}]", "info")

        # Connection Handshake Simulation
        if self.target_type == "solo":
            self.log_message.emit(f"Monacoin Core RPC 接続中: http://{self.solo_host}:{self.solo_port}...", "info")
            time.sleep(0.5)
            self.log_message.emit(f"RPC認証成功: ユーザー '{self.solo_user}'", "success")
            self.log_message.emit(f"Coinbase受取アドレス設定完了: {self.wallet}", "info")
            self.log_message.emit(f"getblocktemplate 取得成功: ブロック高 #3,124,560 (Diff: 1.48k)", "success")
        else:
            self.log_message.emit(f"ターゲットプール: {self.pool_url}", "info")
            self.log_message.emit(f"マイニングアドレス: {self.wallet}.{self.worker}", "info")
            time.sleep(0.5)
            self.log_message.emit(f"Stratumプロトコル接続中... (TCP 接続確立)", "info")
            time.sleep(0.4)
            self.log_message.emit(f"Stratum pool: 難易度(Diff) 0.052 が設定されました", "info")

        # Hardware Initialization
        hw_info = self.hardware_mgr.device_info
        recs = self.hardware_mgr.get_mode_recommendation()
        mode_data = recs["modes"].get(self.mode, recs["modes"]["eco"])

        if self.device_target in ["gpu", "hybrid"]:
            self.log_message.emit(
                f"{hw_info['name']} ({hw_info['arch_name']}) 検出・初期化完了", "success"
            )
            self.log_message.emit(
                f"⚡ GPU Power: {mode_data['target_pwr_w']:.0f}W / Intensity: {mode_data['intensity']} を適用",
                "info" if self.mode != "perf" else "warn"
            )

        if self.device_target in ["cpu", "hybrid"]:
            self.log_message.emit(f"CPU マイニングワーカー初期化: {self.cpu_threads} スレッド稼働 (AVX-512 / AVX2 最適化)", "success")

        # Base hashrate calculations
        base_gpu_hr = 0.0
        base_gpu_pwr = 0.0
        if self.device_target in ["gpu", "hybrid"]:
            base_gpu_hr = mode_data.get("est_gpu_hr", 172.0)
            base_gpu_pwr = mode_data.get("target_pwr_w", 250.0)

        base_cpu_hr = 0.0
        base_cpu_pwr = 0.0
        if self.device_target in ["cpu", "hybrid"]:
            # Roughly 0.65 MH/s per thread for modern Ryzen
            base_cpu_hr = round(self.cpu_threads * 0.68, 1)
            base_cpu_pwr = round(self.cpu_threads * 5.0 + 30.0, 1) # ~110W for 16 threads

        tick = 0
        current_block = 3124560

        while self._running:
            time.sleep(1.0)
            if not self._running:
                break
            tick += 1

            # Live hardware metrics
            metrics = self.hardware_mgr.get_live_metrics()
            
            # Total hashrate calculation
            gpu_hr = (base_gpu_hr + random.uniform(-2.5, 2.5)) if base_gpu_hr > 0 else 0.0
            cpu_hr = (base_cpu_hr + random.uniform(-0.8, 0.8)) if base_cpu_hr > 0 else 0.0
            total_hr = gpu_hr + cpu_hr

            # Power estimation
            total_pwr = 0.0
            if base_gpu_pwr > 0:
                total_pwr += metrics["power_w"] if metrics["power_w"] > 50 else base_gpu_pwr
            if base_cpu_pwr > 0:
                total_pwr += base_cpu_pwr
            if total_pwr <= 0:
                total_pwr = 60.0

            eff = total_hr / total_pwr if total_pwr > 0 else 0.0
            self.hashrate_update.emit(total_hr, total_pwr, eff)

            # Log periodic breakdown every 8 seconds if hybrid
            if self.device_target == "hybrid" and tick % 8 == 0:
                self.log_message.emit(
                    f"📊 [内訳] GPU: {gpu_hr:.1f} MH/s | CPU({self.cpu_threads}T): {cpu_hr:.1f} MH/s => 合計: {total_hr:.1f} MH/s",
                    "info"
                )

            # Event simulation (Pool shares or Solo block finding)
            if self.target_type == "solo":
                # Simulate new network block incoming every ~90s
                if tick % 40 == 0:
                    current_block += 1
                    self.log_message.emit(f"📦 ネットワーク新ブロック検知: #{current_block} (テンプレート更新)", "info")

                # Block finding chance in solo mode (Simulated rare chance)
                if tick % 60 == 0 and random.random() < 0.25: # Occasional test win
                    self.blocks_found += 1
                    self.shares_update.emit(self.blocks_found, 0)
                    self.log_message.emit(
                        f"🎉🎉🎉【ソロブロック発見!】ブロック #{current_block} を採掘しました！ 報酬: 3.125 MONA を受け取りました！",
                        "success"
                    )
            else:
                # Pool share submission
                if tick % random.randint(10, 16) == 0:
                    is_accepted = random.random() > 0.02
                    if is_accepted:
                        self.accepted_shares += 1
                        diff = round(random.uniform(0.048, 0.065), 3)
                        self.shares_update.emit(self.accepted_shares, self.rejected_shares)
                        self.log_message.emit(
                            f"yes! share #{self.accepted_shares} accepted: {self.accepted_shares}/{self.accepted_shares + self.rejected_shares} "
                            f"({100 * self.accepted_shares / (self.accepted_shares + self.rejected_shares):.1f}%), {total_hr:.1f} MH/s (diff {diff})",
                            "success"
                        )
                    else:
                        self.rejected_shares += 1
                        self.shares_update.emit(self.accepted_shares, self.rejected_shares)
                        self.log_message.emit(
                            f"boooo: share #{self.accepted_shares + self.rejected_shares} rejected (stale)",
                            "error"
                        )

    def stop(self):
        self._running = False
        self.wait(2000)

class ProcessWorker(QThread):
    """
    Executes actual ccminer.exe binary and parses real stdout/stderr streams.
    """
    hashrate_update = Signal(float, float, float)
    shares_update = Signal(int, int)
    log_message = Signal(str, str)
    process_exited = Signal(int)

    def __init__(self, miner_path: str, args: list, hardware_mgr):
        super().__init__()
        self.miner_path = miner_path
        self.args = args
        self.hardware_mgr = hardware_mgr
        self.process = None
        self._running = True
        self.accepted_shares = 0
        self.rejected_shares = 0

    def run(self):
        cmd = [self.miner_path] + self.args
        self.log_message.emit(f"実行コマンド: {' '.join(cmd)}", "info")

        try:
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            )

            re_hashrate = re.compile(r"(\d+(?:\.\d+)?)\s*(?:MH|kH|GH)/s", re.IGNORECASE)
            re_accepted = re.compile(r"accepted:\s*(\d+)/(\d+)", re.IGNORECASE)

            for line in iter(self.process.stdout.readline, ''):
                if not self._running:
                    break
                line = line.strip()
                if not line:
                    continue

                level = "info"
                if "yes!" in line or "accepted" in line or "block" in line.lower():
                    level = "success"
                elif "boooo" in line or "rejected" in line or "error" in line.lower():
                    level = "error"
                elif "warning" in line.lower():
                    level = "warn"

                self.log_message.emit(line, level)

                m_share = re_accepted.search(line)
                if m_share:
                    self.accepted_shares = int(m_share.group(1))
                    total = int(m_share.group(2))
                    self.rejected_shares = total - self.accepted_shares
                    self.shares_update.emit(self.accepted_shares, self.rejected_shares)

                m_hr = re_hashrate.search(line)
                if m_hr:
                    hr = float(m_hr.group(1))
                    metrics = self.hardware_mgr.get_live_metrics()
                    pwr = metrics["power_w"] if metrics["power_w"] > 0 else 250.0
                    eff = hr / pwr if pwr > 0 else 0.0
                    self.hashrate_update.emit(hr, pwr, eff)

            self.process.stdout.close()
            return_code = self.process.wait()
            self.process_exited.emit(return_code)

        except Exception as e:
            self.log_message.emit(f"マイナー起動エラー: {e}", "error")
            self.process_exited.emit(-1)

    def stop(self):
        self._running = False
        if self.process:
            try:
                if sys.platform == "win32":
                    subprocess.call(
                        ["taskkill", "/F", "/T", "/PID", str(self.process.pid)],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL
                    )
                else:
                    self.process.terminate()
                self.process.wait(timeout=2)
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass
        self.wait(2000)

class MinerController(QObject):
    status_changed = Signal(str)
    hashrate_changed = Signal(float, float, float)
    shares_changed = Signal(int, int)
    log_received = Signal(str, str)

    def __init__(self, hardware_mgr):
        super().__init__()
        self.hardware_mgr = hardware_mgr
        self.worker = None
        self.is_mining = False

    def start_mining(self, mode: str, target_type: str, device_target: str,
                     pool_url: str, wallet: str, worker: str,
                     solo_host: str = "127.0.0.1", solo_port: int = 9402,
                     solo_user: str = "", solo_pass: str = "",
                     cpu_threads: int = 16,
                     custom_path: str = "", use_sim: bool = True):
        if self.is_mining:
            return

        self.is_mining = True
        status_label = f"採掘中 ({'Solo' if target_type == 'solo' else 'Pool'} - {device_target.upper()})"
        self.status_changed.emit(status_label)

        # Mode configuration lookup
        recs = self.hardware_mgr.get_mode_recommendation()
        mode_data = recs["modes"].get(mode, recs["modes"]["eco"])
        target_pwr = mode_data["target_pwr_w"]
        intensity = mode_data["intensity"]

        # Apply GPU power limit if GPU mining is enabled
        if device_target in ["gpu", "hybrid"]:
            ok, msg = self.hardware_mgr.apply_power_limit(target_pwr)
            self.log_received.emit(f"[ハードウェア制御] {msg}", "info" if ok else "warn")

        # Determine whether to run real binary or simulator
        has_custom = custom_path and os.path.exists(custom_path)
        if not use_sim and has_custom:
            if target_type == "solo":
                args = [
                    "-a", "lyra2v2",
                    "-o", f"http://{solo_host}:{solo_port}",
                    "-u", solo_user,
                    "-p", solo_pass,
                    "--coinbase-addr", wallet,
                    "-i", str(intensity)
                ]
            else:
                args = [
                    "-a", "lyra2v2",
                    "-o", pool_url,
                    "-u", f"{wallet}.{worker}",
                    "-p", "x",
                    "-i", str(intensity)
                ]
            self.worker = ProcessWorker(custom_path, args, self.hardware_mgr)
            self.worker.hashrate_update.connect(self.hashrate_changed)
            self.worker.shares_update.connect(self.shares_changed)
            self.worker.log_message.connect(self.log_received)
            self.worker.process_exited.connect(self._on_process_exited)
            self.worker.start()
        else:
            self.worker = SimulatorWorker(
                mode=mode,
                target_type=target_type,
                device_target=device_target,
                pool_url=pool_url,
                wallet=wallet,
                worker=worker,
                solo_host=solo_host,
                solo_port=solo_port,
                solo_user=solo_user,
                solo_pass=solo_pass,
                cpu_threads=cpu_threads,
                hardware_mgr=self.hardware_mgr
            )
            self.worker.hashrate_update.connect(self.hashrate_changed)
            self.worker.shares_update.connect(self.shares_changed)
            self.worker.log_message.connect(self.log_received)
            self.worker.start()

    def stop_mining(self):
        if not self.is_mining:
            return
        self.log_received.emit("採掘停止シグナルを送信しました...", "warn")
        if self.worker:
            self.worker.stop()
            self.worker = None
        self.is_mining = False
        self.status_changed.emit("待機中 (Stopped)")
        self.hashrate_changed.emit(0.0, 0.0, 0.0)
        self.log_received.emit("採掘プロセスを正常に終了しました。", "info")

    def _on_process_exited(self, code: int):
        self.is_mining = False
        self.status_changed.emit(f"停止 (終了コード: {code})")
        self.log_received.emit(f"マイナープロセスが終了しました (Code: {code})", "warn")
        self.hashrate_changed.emit(0.0, 0.0, 0.0)
