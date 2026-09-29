"""
Native OpenCL Miner Worker for MonaMiner.
Integrates pure-Python Stratum Client with the JIT OpenCL Lyra2REv2 GPU Kernel.
Runs in a background QThread and emits live telemetry signals.
"""

import os
import sys
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from ctypes import c_uint
from PySide6.QtCore import QThread, Signal

from app.miner.opencl_backend import OpenCLBackend, OpenCLContext
from app.miner.benchmark import build_search_kernel
from app.miner.cpu_backend import CpuBackend, CpuBackendUnavailable
from app.miner.stratum_client import StratumClient, StratumJob, target_words
from app.miner.rpc_solo_client import RpcSoloClient, SoloBlockTemplate

NONCE_SPACE = 1 << 32       # a header has 2^32 nonces; after that the work must change
MAX_FOUND = 16              # capacity of the kernel's found_nonce buffer
TARGET_DISPATCH_S = 0.10    # adaptive batching aims at ~100 ms per kernel launch
MAX_BATCH = 4194304
CPU_MIN_CHUNK = 64          # nonces per CPU thread and launch (adapted to ~100 ms)
CPU_MAX_CHUNK = 1 << 20
CPU_WATT_PER_THREAD = 5.0   # rough estimate, only used when no power sensor is available
POOL_DEFAULT_HOST = "stratum1.vippool.net"
POOL_DEFAULT_PORT = 8888


class OpenCLMinerWorker(QThread):
    hashrate_update = Signal(float, float, float) # hashrate_mhs, power_w, eff_mhw
    shares_update = Signal(int, int) # accepted, rejected
    log_message = Signal(str, str) # text, level

    def __init__(self, mode: str, target_type: str, device_target: str,
                 pool_url: str, wallet: str, worker: str,
                 solo_host: str = "127.0.0.1", solo_port: int = 9402,
                 solo_user: str = "", solo_pass: str = "",
                 cpu_threads: int = 16, hardware_mgr=None, selected_gpu_indices: list = None,
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
        self.solo_client: RpcSoloClient = None
        self.current_template: SoloBlockTemplate = None
        self.ctx_list = [] # one dict per GPU: context, kernel, buffers, local_wg, batch_size, ...
        self.use_gpu = device_target in ("gpu", "hybrid")
        self.use_cpu = device_target in ("cpu", "hybrid")
        self.cpu_threads = max(1, int(cpu_threads or 1))
        self._cpu_pool = None
        self._cpu_chunk = 512

    # ------------------------------------------------------------------ thread entry
    def run(self):
        try:
            if self._init_devices() and self._connect():
                self._mine_loop()
        except Exception as e:
            self.log_message.emit(f"マイナーエンジンで予期しないエラーが発生しました: {e}", "error")
        finally:
            self._cleanup()

    def _sleep(self, seconds: float):
        """Sleep in short slices so stop() is honoured promptly."""
        end = time.monotonic() + seconds
        while self._running and time.monotonic() < end:
            time.sleep(min(0.05, max(0.0, end - time.monotonic())))

    def _kernel_path(self) -> str:
        if getattr(sys, 'frozen', False):
            base_dir = os.path.dirname(sys.executable)
            kernel_path = os.path.join(base_dir, "app", "miner", "kernels", "lyra2v2.cl")
            if not os.path.exists(kernel_path):
                kernel_path = os.path.join(getattr(sys, '_MEIPASS', base_dir), "app", "miner", "kernels", "lyra2v2.cl")
            return kernel_path
        return os.path.join(os.path.dirname(__file__), "kernels", "lyra2v2.cl")

    def _mode_data(self) -> dict:
        recs = self.hardware_mgr.get_mode_recommendation()
        return recs["modes"].get(self.mode, recs["modes"]["eco"])

    # ------------------------------------------------------------------ setup
    def _init_devices(self) -> bool:
        devices = {"gpu": "GPU", "cpu": "CPU", "hybrid": "GPU + CPU"}.get(self.device_target, "GPU")
        self.log_message.emit(f"★ 独自内蔵マイナーエンジン起動 (Lyra2REv2 / {devices})", "info")
        if self.use_cpu:
            try:
                CpuBackend.load()
                self._cpu_pool = ThreadPoolExecutor(max_workers=self.cpu_threads)
                self.log_message.emit(f"CPU マイニングワーカー初期化: {self.cpu_threads} スレッド", "success")
            except CpuBackendUnavailable as e:
                self.log_message.emit(f"CPU エンジンを初期化できません: {e}", "error")
                if not self.use_gpu:
                    return False
                self.use_cpu = False
        if self.use_gpu:
            if not self._init_gpus():
                if not self.use_cpu:
                    return False
                self.log_message.emit("GPU を使用できないため CPU のみで採掘します。", "warn")
        return True

    def _init_gpus(self) -> bool:
        self.log_message.emit(f"ターゲット: [{'ソロ (Solo RPC)' if self.target_type == 'solo' else 'プール (Stratum)'}]", "info")

        try:
            all_devices = OpenCLBackend.get_all_gpu_devices()
            if not all_devices:
                self.log_message.emit("利用可能な OpenCL GPU が見つかりません。", "error")
                return False

            target_devs = [d for d in all_devices if d["global_index"] in self.selected_gpu_indices]
            if not target_devs:
                target_devs = [all_devices[0]]

            self.log_message.emit(f"採掘稼働 GPU 台数: {len(target_devs)} 台", "success")

            with open(self._kernel_path(), "r", encoding="utf-8") as f:
                kernel_src = f.read()

            intensity = self._mode_data().get("intensity", 20)

            for d in target_devs:
                self.log_message.emit(f"GPU #{d['global_index']} 初期化: {d['name']} ({d['platform_name']})", "info")
                ctx = OpenCLContext(d["platform_id"], d["id"])
                # Registered before the build so a failing JIT compile still releases the context.
                item = {"ctx": ctx, "dev": d, "last_key": None}
                self.ctx_list.append(item)

                item["kernel"], variant = build_search_kernel(ctx, d, kernel_src)
                self.log_message.emit(f"GPU #{d['global_index']} カーネル: {variant}", "info")

                local_wg = max(1, min(128, d.get("max_work_group_size", 128)))
                init_batch = max(local_wg * 16, 1 << min(20, max(16, intensity)))
                item["local_wg"] = local_wg
                item["batch_size"] = (init_batch // local_wg) * local_wg
                item["buf_header"] = ctx.create_buffer(19 * 4)
                item["buf_found_nonce"] = ctx.create_buffer(MAX_FOUND * 4)
                item["buf_found_count"] = ctx.create_buffer(4)

            self.log_message.emit("✓ 全GPU JIT コンパイル＆バッファ初期化完了！", "success")
            return True
        except Exception as e:
            self.log_message.emit(f"OpenCL Multi-GPU 初期化失敗: {e}", "error")
            return False

    def _connect(self) -> bool:
        if self.target_type == "solo":
            self.solo_client = RpcSoloClient(
                host=self.solo_host,
                port=self.solo_port,
                user=self.solo_user,
                password=self.solo_pass,
                wallet_address=self.wallet
            )
            self.log_message.emit(f"Monacoin Core RPC 接続確認中: http://{self.solo_host}:{self.solo_port}...", "info")
            ok, msg, _ = self.solo_client.test_connection()
            if not ok:
                self.log_message.emit(f"ノード接続エラー: {msg}", "error")
                return False
            self.log_message.emit(f"✓ {msg}", "success")
            return True

        clean_url = (self.pool_url or "").replace("stratum+tcp://", "").replace("tcp://", "").strip()
        if ":" in clean_url:
            host, port_str = clean_url.split(":", 1)
            port = int(port_str) if port_str.isdigit() else POOL_DEFAULT_PORT
        else:
            host = clean_url
            port = POOL_DEFAULT_PORT

        if not host.strip():
            host = POOL_DEFAULT_HOST
            self.log_message.emit(f"⚠ プールホスト名が空のため、デフォルト ({POOL_DEFAULT_HOST}:{POOL_DEFAULT_PORT}) を使用します。", "warn")

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
        if not self.stratum.connect():
            self.log_message.emit("プールへの接続に失敗しました。", "error")
            return False
        return True

    def _cleanup(self):
        if self.stratum:
            self.stratum.close()
            self.stratum = None
        if self._cpu_pool:
            self._cpu_pool.shutdown(wait=True)
            self._cpu_pool = None
        for item in self.ctx_list:
            try:
                item["ctx"].release()
            except Exception:
                pass
        self.ctx_list.clear()

    # ------------------------------------------------------------------ mining
    @staticmethod
    def _extranonce2_hex(counter: int, size: int) -> str:
        if size <= 0:
            return ""
        return f"{counter % (1 << (8 * size)):0{size * 2}x}"

    def _mine_loop(self):
        mode_data = self._mode_data()
        solo = self.target_type == "solo"

        if self.ctx_list:
            first = self.ctx_list[0]
            self.log_message.emit(
                f"最適化プロファイル: {self.mode.upper()} (初期バッチ: {first['batch_size']:,} / WG: {first['local_wg']} / 適応型ディスパッチ有効)",
                "info"
            )

        work_key = None        # identifies the header currently loaded on the GPUs
        cached_key = None      # identifies the header last built on the CPU
        header_76 = b""
        cursor = 0             # next unsearched nonce of the current header (shared by all GPUs)
        en2_counter = 0        # pool: extranonce2 of the current header
        last_job_key = None
        tpl_serial = 0
        t_last_poll = 0.0
        t_hi, t_lo = 0, 0

        cpu_inflight = []      # (nonce count, future, work) of CPU scans still running
        total_hashes_window = 0
        t_start_window = time.perf_counter()

        while self._running:
            # ---- 1. current work -------------------------------------------------
            work = {}
            if solo:
                now_mono = time.monotonic()
                # Poll the template every 1.5 s; the current one is dropped after a found block
                # or when its nonce space is exhausted.
                if self.current_template is None or (now_mono - t_last_poll) >= 1.5:
                    t_last_poll = now_mono
                    tpl, err = self.solo_client.get_block_template()
                    if err:
                        if self.solo_client.address_invalid:
                            self.log_message.emit(f"[Solo RPC] {err}", "error")
                            return
                        self.log_message.emit(f"[Solo RPC] {err}", "warn")
                        self._sleep(0.5)
                        continue
                    new_tip = self.current_template is None or tpl.prev_hash_hex != self.current_template.prev_hash_hex
                    if new_tip:
                        self.log_message.emit(
                            f"[Solo] 新ブロックテンプレート受信: 高さ #{tpl.height:,} "
                            f"(Target: 0x{tpl.target_high:08x}{tpl.target_low:08x}..., 報酬: {tpl.coinbase_value / 1e8:.2f} MONA)",
                            "info"
                        )
                        self.current_template = tpl
                        tpl_serial += 1
                        cursor = 0
                tpl = self.current_template
                work_key = ("solo", tpl_serial)
                header_76 = tpl.header_76
                t_hi, t_lo = tpl.target_high, tpl.target_low
                work["tpl"] = tpl
            else:
                if not self.stratum.is_alive:
                    if self._running:  # not caused by stop()
                        self.log_message.emit("プールとの接続が切断されました。採掘を停止します。", "error")
                    return
                if self.stratum.authorized is False:
                    self.log_message.emit("プール認証に失敗したため採掘を停止します。ワーカー名・パスワードを確認してください。", "error")
                    return
                job = self.stratum.current_job
                if job is None:
                    self._sleep(0.05)
                    continue
                t_hi, t_lo = target_words(self.stratum.target)

                job_key = (job.job_id, job.ntime)
                if job_key != last_job_key:
                    last_job_key = job_key
                    cursor = 0
                en2_hex = self._extranonce2_hex(en2_counter, self.stratum.extranonce2_size)
                work_key = (job.job_id, job.ntime, en2_counter)
                if work_key != cached_key:
                    header_76 = job.build_header_prefix(self.stratum.extranonce1, en2_hex)
                    cached_key = work_key
                work["job"] = job
                work["en2_hex"] = en2_hex

            # ---- 2. nonce space exhausted: change the header ---------------------
            if cursor >= NONCE_SPACE:
                if solo:
                    self.current_template = None   # fetch a fresh template (new curtime)
                else:
                    en2_counter += 1
                cursor = 0
                continue

            # ---- 3. launch one kernel per GPU (they run concurrently) ------------
            pending = []
            for item in self.ctx_list:
                ctx = item["ctx"]
                kernel = item["kernel"]
                wg = item["local_wg"]

                batch = min(item["batch_size"], NONCE_SPACE - cursor)
                batch -= batch % wg
                if batch <= 0:
                    cursor = NONCE_SPACE
                    break

                if item["last_key"] != work_key:
                    ctx.write_buffer(item["buf_header"], (c_uint * 19).from_buffer_copy(header_76), 19 * 4)
                    item["last_key"] = work_key

                ctx.write_buffer(item["buf_found_count"], (c_uint * 1)(0), 4)
                ctx.set_arg_mem(kernel, 0, item["buf_header"])
                ctx.set_arg_uint(kernel, 1, cursor)
                ctx.set_arg_uint(kernel, 2, t_hi)
                ctx.set_arg_uint(kernel, 3, t_lo)
                ctx.set_arg_mem(kernel, 4, item["buf_found_nonce"])
                ctx.set_arg_mem(kernel, 5, item["buf_found_count"])

                t_launch = time.perf_counter()
                ctx.run_kernel_1d(kernel, batch, wg)
                pending.append((item, batch, t_launch))
                cursor += batch

            # CPU threads scan their own slices in the background. The loop never waits for them: a CPU
            # chunk takes ~100 ms but a GPU launch only ~15 ms, and blocking here left the GPU idle ~85%.
            if self._cpu_pool:
                while len(cpu_inflight) < self.cpu_threads:
                    chunk = min(self._cpu_chunk, NONCE_SPACE - cursor)
                    if chunk <= 0:
                        cursor = NONCE_SPACE
                        break
                    cpu_inflight.append((chunk, self._cpu_pool.submit(
                        self._cpu_scan, header_76, cursor, chunk, t_hi, t_lo), work))
                    cursor += chunk

            # ---- 4. collect results ---------------------------------------------
            for item, batch, t_launch in pending:
                ctx = item["ctx"]
                ctx.finish()
                elapsed = time.perf_counter() - t_launch

                c_count = (c_uint * 1)(0)
                ctx.read_buffer(item["buf_found_count"], c_count, 4)
                if c_count[0] > 0:
                    c_nonces = (c_uint * MAX_FOUND)()
                    ctx.read_buffer(item["buf_found_nonce"], c_nonces, MAX_FOUND * 4)
                    nonces = [int(c_nonces[i]) for i in range(min(c_count[0], MAX_FOUND))]
                    self._handle_found(f"GPU #{item['dev']['global_index']}", nonces, work)

                total_hashes_window += batch

                # Adaptive batch tuning: ~100 ms per launch keeps stale shares low
                if elapsed > 0.001:
                    wg = item["local_wg"]
                    ideal_batch = int(item["batch_size"] * (TARGET_DISPATCH_S / elapsed))
                    new_batch = int(item["batch_size"] * 0.7 + ideal_batch * 0.3)
                    new_batch = max(wg * 16, min(MAX_BATCH, new_batch))
                    item["batch_size"] = (new_batch // wg) * wg

                if solo and self.current_template is None:
                    break  # a block was found: drop the remaining results, fetch a new template

            if cpu_inflight:
                if not pending:
                    # CPU-only: nothing else paces the loop, so sleep until a chunk finishes
                    wait([f for _, f, _ in cpu_inflight], timeout=0.05, return_when=FIRST_COMPLETED)
                still_running = []
                for job in cpu_inflight:
                    chunk, future, job_work = job
                    if not future.done():
                        still_running.append(job)
                        continue
                    count, nonces, elapsed = future.result()
                    total_hashes_window += chunk
                    if nonces and not (solo and self.current_template is None):
                        self._handle_found("CPU", nonces, job_work)
                    if elapsed > 0.001:
                        # from this job's own size: several jobs finishing in one pass ran with older sizes
                        ideal = int(chunk * (TARGET_DISPATCH_S / elapsed))
                        self._cpu_chunk = max(CPU_MIN_CHUNK, min(CPU_MAX_CHUNK, int(self._cpu_chunk * 0.7 + ideal * 0.3)))
                cpu_inflight = still_running

            # ---- 5. telemetry (about once per second) ----------------------------
            now = time.perf_counter()
            dt = now - t_start_window
            if dt >= 1.0:
                mhs = (total_hashes_window / dt) / 1_000_000.0
                metrics = self.hardware_mgr.get_live_metrics()
                pwr = metrics.get("power_w", 0.0) if self.ctx_list else 0.0
                if pwr <= 0 and self.ctx_list:
                    pwr = mode_data.get("target_pwr_w", 200.0) * len(self.ctx_list)
                if self._cpu_pool:
                    pwr += 30.0 + CPU_WATT_PER_THREAD * self.cpu_threads
                eff = mhs / pwr if pwr > 0 else 0.0
                self.hashrate_update.emit(mhs, pwr, eff)

                total_hashes_window = 0
                t_start_window = now

    @staticmethod
    def _cpu_scan(header_76: bytes, start: int, count: int, t_hi: int, t_lo: int):
        t0 = time.perf_counter()
        n, nonces = CpuBackend.scan(header_76, start, count, t_hi, t_lo)
        return n, nonces, time.perf_counter() - t0

    def _handle_found(self, source: str, nonces: list, work: dict):
        for nonce in nonces:
            self.log_message.emit(f"★ {source} 有効な Nonce 発見！: 0x{nonce:08x}", "success")

            if self.target_type == "solo":
                tpl = work["tpl"]
                ok, submit_msg = self.solo_client.submit_block(tpl, nonce)
                if ok:
                    self.accepted_shares += 1
                else:
                    self.rejected_shares += 1
                self.shares_update.emit(self.accepted_shares, self.rejected_shares)
                self.log_message.emit(submit_msg, "success" if ok else "error")
                # Either way the template is finished (new tip, or rejected): fetch a new one.
                self.current_template = None
                return
            else:
                if self.stratum:
                    job = work["job"]
                    self.stratum.submit_share(
                        job_id=job.job_id,
                        extranonce2=work["en2_hex"],
                        ntime=job.ntime,
                        nonce_uint=nonce,
                        callback=self._on_share_response
                    )

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
