"""
Native OpenCL Miner Worker for MonaMiner.
Integrates pure-Python Stratum Client with the JIT OpenCL Lyra2REv2 GPU Kernel.
Runs in a background QThread and emits live telemetry signals.
"""

import os
import sys
import time
import struct
import ctypes
from ctypes import c_uint, byref
from PySide6.QtCore import QThread, Signal

from app.miner.opencl_backend import OpenCLBackend, OpenCLContext, OpenCLException
from app.miner.stratum_client import StratumClient, StratumJob, diff_to_target

class OpenCLMinerWorker(QThread):
    hashrate_update = Signal(float, float, float) # hashrate_mhs, power_w, eff_mhw
    shares_update = Signal(int, int) # accepted, rejected
    log_message = Signal(str, str) # text, level

    def __init__(self, mode: str, target_type: str, device_target: str,
                 pool_url: str, wallet: str, worker: str,
                 solo_host: str, solo_port: int, solo_user: str, solo_pass: str,
                 cpu_threads: int, hardware_mgr):
        super().__init__()
        self.mode = mode
        self.target_type = target_type
        self.device_target = device_target
        self.pool_url = pool_url
        self.wallet = wallet
        self.worker_name = worker
        self.solo_host = solo_host
        self.solo_port = solo_port
        self.solo_user = solo_user
        self.solo_pass = solo_pass
        self.cpu_threads = cpu_threads
        self.hardware_mgr = hardware_mgr

        self._running = True
        self.accepted_shares = 0
        self.rejected_shares = 0
        self.stratum: StratumClient = None
        self.ctx: OpenCLContext = None

    def run(self):
        self.log_message.emit("★ 独自内蔵 OpenCL マイナーエンジン起動 (Lyra2REv2)", "info")
        self.log_message.emit(f"ターゲット: [{'ソロ (Solo RPC)' if self.target_type == 'solo' else 'プール (Stratum)'}]", "info")

        # 1. Setup OpenCL Device
        try:
            platforms = OpenCLBackend.get_platforms()
            if not platforms:
                self.log_message.emit("OpenCL プラットフォームが見つかりません。", "error")
                return

            p = platforms[0]
            devices = OpenCLBackend.get_devices(p["id"])
            if not devices:
                self.log_message.emit("利用可能な OpenCL GPU が見つかりません。", "error")
                return

            d = devices[0]
            self.log_message.emit(f"OpenCL デバイスバインド: {d['name']} ({p['name']})", "success")
            self.log_message.emit(f"  - Compute Units: {d['compute_units']} / VRAM: {d['global_mem_gb']} GB", "info")

            self.ctx = OpenCLContext(p["id"], d["id"])

            # 2. Compile Lyra2REv2 Kernel
            self.log_message.emit("Lyra2REv2 OpenCL C カーネルを JIT コンパイル中...", "info")
            if getattr(sys, 'frozen', False):
                base_dir = os.path.dirname(sys.executable)
                kernel_path = os.path.join(base_dir, "app", "miner", "kernels", "lyra2v2.cl")
                if not os.path.exists(kernel_path):
                    kernel_path = os.path.join(getattr(sys, '_MEIPASS', base_dir), "app", "miner", "kernels", "lyra2v2.cl")
            else:
                kernel_path = os.path.join(os.path.dirname(__file__), "kernels", "lyra2v2.cl")

            with open(kernel_path, "r", encoding="utf-8") as f:
                src = f.read()

            self.ctx.build_program(src)
            kernel = self.ctx.get_kernel("search_lyra2v2")
            self.log_message.emit("✓ JIT コンパイル成功！ GPU演算パイプライン準備完了", "success")

        except Exception as e:
            self.log_message.emit(f"OpenCL 初期化失敗: {e}", "error")
            return

        # 3. Setup Stratum Client
        if self.target_type != "solo":
            # Parse pool URL e.g. stratum+tcp://stratum1.vippool.net:8888
            clean_url = self.pool_url.replace("stratum+tcp://", "").replace("tcp://", "")
            if ":" in clean_url:
                host, port_str = clean_url.split(":", 1)
                port = int(port_str)
            else:
                host = clean_url
                port = 8888

            full_user = f"{self.wallet}.{self.worker_name}" if self.wallet else self.worker_name
            self.stratum = StratumClient(
                host=host,
                port=port,
                username=full_user,
                password="x",
                on_log=lambda msg, lvl: self.log_message.emit(f"[Stratum] {msg}", lvl),
                on_new_job=self._on_new_stratum_job
            )
            connected = self.stratum.connect()
            if not connected:
                self.log_message.emit("プールへの接続に失敗しました。", "error")
                self.ctx.release()
                return

        # 4. Intensity & Workgroup settings based on profile
        recs = self.hardware_mgr.get_mode_recommendation()
        mode_data = recs["modes"].get(self.mode, recs["modes"]["eco"])
        intensity = mode_data.get("intensity", 20)
        batch_size = 1 << min(22, max(16, intensity)) # 65K to 4M nonces per dispatch
        local_wg = min(256, d.get("max_work_group_size", 256))

        self.log_message.emit(
            f"採掘プロファイル: {self.mode.upper()} (Intensity: {intensity} / BatchSize: {batch_size:,})",
            "info"
        )

        # Buffers
        buf_header = self.ctx.create_buffer(19 * 4)
        buf_found_nonce = self.ctx.create_buffer(4)
        buf_found_count = self.ctx.create_buffer(4)

        base_nonce = 0
        total_hashes_window = 0
        t_start_window = time.perf_counter()

        while self._running:
            # Check current job
            current_job = self.stratum.current_job if self.stratum else None
            current_target = self.stratum.target if self.stratum else 0x00000000FFFF0000000000000000000000000000000000000000000000000000

            if not current_job and self.target_type != "solo":
                # Waiting for first job from pool
                time.sleep(0.1)
                continue

            # Target upper 32-bit for quick kernel thresholding
            target_high = (current_target >> 224) & 0xFFFFFFFF
            if target_high == 0:
                target_high = 0x0000FFFF

            # Build 76-byte header
            if current_job:
                en2_hex = f"{self.stratum.extranonce2_counter:0{self.stratum.extranonce2_size * 2}x}"
                header_76 = current_job.build_header_prefix(self.stratum.extranonce1, en2_hex)
            else:
                header_76 = b"\x00" * 76
                en2_hex = "0000"

            # Load header to GPU
            c_header = (c_uint * 19).from_buffer_copy(header_76)
            self.ctx.write_buffer(buf_header, c_header, 19 * 4)

            # Clear found count
            c_zero = (c_uint * 1)(0)
            self.ctx.write_buffer(buf_found_count, c_zero, 4)

            # Set kernel args
            self.ctx.set_arg_mem(kernel, 0, buf_header)
            self.ctx.set_arg_uint(kernel, 1, base_nonce)
            self.ctx.set_arg_uint(kernel, 2, target_high)
            self.ctx.set_arg_mem(kernel, 3, buf_found_nonce)
            self.ctx.set_arg_mem(kernel, 4, buf_found_count)

            # Dispatch GPU kernel
            self.ctx.run_kernel_1d(kernel, batch_size, local_wg)
            self.ctx.finish()

            # Check if any nonce met target
            c_count = (c_uint * 1)(0)
            self.ctx.read_buffer(buf_found_count, c_count, 4)
            if c_count[0] > 0:
                c_res_nonce = (c_uint * 1)(0)
                self.ctx.read_buffer(buf_found_nonce, c_res_nonce, 4)
                found_nonce = c_res_nonce[0]
                self.log_message.emit(f"★ 有効な Nonce を発見！: 0x{found_nonce:08x}", "success")

                if self.stratum and current_job:
                    self.stratum.submit_share(
                        job_id=current_job.job_id,
                        extranonce2=en2_hex,
                        ntime=current_job.ntime,
                        nonce_uint=found_nonce,
                        callback=self._on_share_response
                    )

            base_nonce = (base_nonce + batch_size) & 0xFFFFFFFF
            total_hashes_window += batch_size

            # Periodic telemetry update (every ~1 sec)
            now = time.perf_counter()
            dt = now - t_start_window
            if dt >= 1.0:
                mhs = (total_hashes_window / dt) / 1_000_000.0
                metrics = self.hardware_mgr.get_live_metrics()
                pwr = metrics.get("power_w", 0.0)
                if pwr <= 0:
                    pwr = mode_data.get("target_pwr_w", 200.0)
                eff = mhs / pwr if pwr > 0 else 0.0
                self.hashrate_update.emit(mhs, pwr, eff)

                total_hashes_window = 0
                t_start_window = now

        # Cleanup
        if self.stratum:
            self.stratum.close()
            self.stratum = None
        if self.ctx:
            self.ctx.release()
            self.ctx = None

    def _on_new_stratum_job(self, job: StratumJob, target: int):
        self.log_message.emit(f"新ジョブ受信: Job ID #{job.job_id} (Clean: {job.clean_jobs})", "info")

    def _on_share_response(self, is_ok: bool, error):
        if is_ok:
            self.accepted_shares += 1
        else:
            self.rejected_shares += 1
        self.shares_update.emit(self.accepted_shares, self.rejected_shares)

    def stop(self):
        self._running = False
        if self.stratum:
            self.stratum.close()
        self.wait(2000)
