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
                 cpu_threads: int, hardware_mgr, selected_gpu_indices: list = None,
                 pool_password: str = "x"):
        super().__init__()
        self.mode = mode
        self.target_type = target_type
        self.device_target = device_target
        self.pool_url = pool_url
        self.wallet = wallet
        self.worker_name = worker
        self.pool_password = pool_password or "x"
        self.solo_host = solo_host
        self.solo_port = solo_port
        self.solo_user = solo_user
        self.solo_pass = solo_pass
        self.cpu_threads = cpu_threads
        self.hardware_mgr = hardware_mgr
        self.selected_gpu_indices = selected_gpu_indices or [0]

        self._running = True
        self.accepted_shares = 0
        self.rejected_shares = 0
        self.stratum: StratumClient = None
        self.ctx_list = [] # List of (OpenCLContext, kernel, dev_info, buffers, base_nonce, batch_size)

    def run(self):
        self.log_message.emit("★ 独自内蔵 OpenCL マイナーエンジン起動 (Lyra2REv2 Multi-GPU)", "info")
        self.log_message.emit(f"ターゲット: [{'ソロ (Solo RPC)' if self.target_type == 'solo' else 'プール (Stratum)'}]", "info")

        # 1. Discover all GPUs
        try:
            all_devices = OpenCLBackend.get_all_gpu_devices()
            if not all_devices:
                self.log_message.emit("利用可能な OpenCL GPU が見つかりません。", "error")
                return

            target_devs = [d for d in all_devices if d["global_index"] in self.selected_gpu_indices]
            if not target_devs:
                target_devs = [all_devices[0]]

            self.log_message.emit(f"採掘稼働 GPU 台数: {len(target_devs)} 台", "success")

            # 2. Kernel source
            if getattr(sys, 'frozen', False):
                base_dir = os.path.dirname(sys.executable)
                kernel_path = os.path.join(base_dir, "app", "miner", "kernels", "lyra2v2.cl")
                if not os.path.exists(kernel_path):
                    kernel_path = os.path.join(getattr(sys, '_MEIPASS', base_dir), "app", "miner", "kernels", "lyra2v2.cl")
            else:
                kernel_path = os.path.join(os.path.dirname(__file__), "kernels", "lyra2v2.cl")

            with open(kernel_path, "r", encoding="utf-8") as f:
                kernel_src = f.read()

            # 3. Setup context for each GPU
            recs = self.hardware_mgr.get_mode_recommendation()
            mode_data = recs["modes"].get(self.mode, recs["modes"]["eco"])
            intensity = mode_data.get("intensity", 20)

            for idx, d in enumerate(target_devs):
                self.log_message.emit(f"GPU #{d['global_index']} 初期化: {d['name']} ({d['platform_name']})", "info")
                ctx = OpenCLContext(d["platform_id"], d["id"])
                ctx.build_program(kernel_src, options="-cl-mad-enable -cl-no-signed-zeros")
                kernel = ctx.get_kernel("search_lyra2v2")

                local_wg = min(256, d.get("max_work_group_size", 256))
                init_batch = max(local_wg * 16, 1 << min(20, max(16, intensity)))

                buf_header = ctx.create_buffer(19 * 4)
                buf_found_nonce = ctx.create_buffer(4)
                buf_found_count = ctx.create_buffer(4)

                # Assign separated base nonce partition for each GPU
                # E.g., GPU 0 starts at 0, GPU 1 at 0x40000000, GPU 2 at 0x80000000...
                base_nonce = (idx * 0x40000000) & 0xFFFFFFFF

                self.ctx_list.append({
                    "ctx": ctx,
                    "kernel": kernel,
                    "dev": d,
                    "local_wg": local_wg,
                    "batch_size": init_batch,
                    "buf_header": buf_header,
                    "buf_found_nonce": buf_found_nonce,
                    "buf_found_count": buf_found_count,
                    "base_nonce": base_nonce,
                    "last_job_key": None
                })
            self.log_message.emit("✓ 全GPU JIT コンパイル＆バッファ初期化完了！", "success")

        except Exception as e:
            self.log_message.emit(f"OpenCL Multi-GPU 初期化失敗: {e}", "error")
            return

        # 3. Setup Stratum Client
        if self.target_type != "solo":
            clean_url = (self.pool_url or "").replace("stratum+tcp://", "").replace("tcp://", "").strip()
            if ":" in clean_url:
                host, port_str = clean_url.split(":", 1)
                port = int(port_str) if port_str.isdigit() else 8888
            else:
                host = clean_url
                port = 8888

            if not host.strip():
                host = "stratum1.vippool.net"
                self.log_message.emit("⚠ プールホスト名が空のため、デフォルト (stratum1.vippool.net:8888) を使用します。", "warn")

            if "." in self.worker_name:
                full_user = self.worker_name
            elif self.wallet:
                full_user = f"{self.wallet}.{self.worker_name}"
            else:
                full_user = self.worker_name

            self.stratum = StratumClient(
                host=host,
                port=port,
                username=full_user,
                password=self.pool_password,
                on_log=lambda msg, lvl: self.log_message.emit(f"[Stratum] {msg}", lvl),
                on_new_job=self._on_new_stratum_job
            )
            connected = self.stratum.connect()
            if not connected:
                self.log_message.emit("プールへの接続に失敗しました。", "error")
                self.ctx.release()
                return

        # 4. Intensity & Adaptive Workgroup settings
        recs = self.hardware_mgr.get_mode_recommendation()
        mode_data = recs["modes"].get(self.mode, recs["modes"]["eco"])
        intensity = mode_data.get("intensity", 20)
        local_wg = min(256, d.get("max_work_group_size", 256))
        # Initial batch size (65K to 1M)
        batch_size = max(local_wg * 16, 1 << min(20, max(16, intensity)))

        self.log_message.emit(
            f"最適化プロファイル: {self.mode.upper()} (初期バッチ: {batch_size:,} / WG: {local_wg} / 適応型ディスパッチ有効)",
            "info"
        )

        total_hashes_window = 0
        t_start_window = time.perf_counter()

        while self._running:
            # Check current job
            current_job = self.stratum.current_job if self.stratum else None
            current_target = self.stratum.target if self.stratum else 0x00000000FFFF0000000000000000000000000000000000000000000000000000

            if not current_job and self.target_type != "solo":
                time.sleep(0.05)
                continue

            # Target upper 32-bit threshold
            target_high = (current_target >> 224) & 0xFFFFFFFF
            if target_high == 0:
                target_high = 0x0000FFFF

            en2_hex = f"{self.stratum.extranonce2_counter:0{self.stratum.extranonce2_size * 2}x}" if current_job else "0000"
            job_key = (current_job.job_id, en2_hex, current_job.ntime) if current_job else "solo_dummy"

            for item in self.ctx_list:
                ctx = item["ctx"]
                kernel = item["kernel"]
                local_wg = item["local_wg"]
                batch_size = item["batch_size"]
                buf_header = item["buf_header"]
                buf_found_nonce = item["buf_found_nonce"]
                buf_found_count = item["buf_found_count"]

                # Build 76-byte header only when job or extranonce2 changes
                if job_key != item["last_job_key"]:
                    if current_job:
                        header_76 = current_job.build_header_prefix(self.stratum.extranonce1, en2_hex)
                    else:
                        header_76 = b"\x00" * 76
                    c_header = (c_uint * 19).from_buffer_copy(header_76)
                    ctx.write_buffer(buf_header, c_header, 19 * 4)
                    item["last_job_key"] = job_key
                    # Reset base_nonce
                    item["base_nonce"] = (item["dev"]["global_index"] * 0x40000000) & 0xFFFFFFFF

                # Clear found count (4 bytes)
                c_zero = (c_uint * 1)(0)
                ctx.write_buffer(buf_found_count, c_zero, 4)

                # Set kernel arguments
                ctx.set_arg_mem(kernel, 0, buf_header)
                ctx.set_arg_uint(kernel, 1, item["base_nonce"])
                ctx.set_arg_uint(kernel, 2, target_high)
                ctx.set_arg_mem(kernel, 3, buf_found_nonce)
                ctx.set_arg_mem(kernel, 4, buf_found_count)

                # Measure dispatch duration to dynamically adapt batch size towards ~100ms
                t_disp_start = time.perf_counter()
                ctx.run_kernel_1d(kernel, batch_size, local_wg)
                ctx.finish()
                disp_elapsed = time.perf_counter() - t_disp_start

                # Check if any nonce met target
                c_count = (c_uint * 1)(0)
                ctx.read_buffer(buf_found_count, c_count, 4)
                if c_count[0] > 0:
                    c_res_nonce = (c_uint * 1)(0)
                    ctx.read_buffer(buf_found_nonce, c_res_nonce, 4)
                    found_nonce = c_res_nonce[0]
                    self.log_message.emit(
                        f"★ GPU #{item['dev']['global_index']} 有効な Nonce 発見！: 0x{found_nonce:08x}",
                        "success"
                    )

                    if self.stratum and current_job:
                        self.stratum.submit_share(
                            job_id=current_job.job_id,
                            extranonce2=en2_hex,
                            ntime=current_job.ntime,
                            nonce_uint=found_nonce,
                            callback=self._on_share_response
                        )

                item["base_nonce"] = (item["base_nonce"] + batch_size) & 0xFFFFFFFF
                total_hashes_window += batch_size

                # Adaptive batch tuning (Target ~80-120ms to eliminate stale shares)
                if disp_elapsed > 0.001:
                    ideal_batch = int(batch_size * (0.10 / disp_elapsed))
                    batch_size = max(local_wg * 16, min(4194304, int(batch_size * 0.7 + ideal_batch * 0.3)))
                    item["batch_size"] = (batch_size // local_wg) * local_wg

            # Periodic telemetry update (every ~1 sec)
            now = time.perf_counter()
            dt = now - t_start_window
            if dt >= 1.0:
                mhs = (total_hashes_window / dt) / 1_000_000.0
                metrics = self.hardware_mgr.get_live_metrics()
                pwr = metrics.get("power_w", 0.0)
                if pwr <= 0:
                    pwr = mode_data.get("target_pwr_w", 200.0) * max(1, len(self.ctx_list))
                eff = mhs / pwr if pwr > 0 else 0.0
                self.hashrate_update.emit(mhs, pwr, eff)

                total_hashes_window = 0
                t_start_window = now

        # Cleanup
        if self.stratum:
            self.stratum.close()
            self.stratum = None
        for item in self.ctx_list:
            try:
                item["ctx"].release()
            except Exception:
                pass
        self.ctx_list.clear()

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
