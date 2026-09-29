"""
Measures the real Lyra2REv2 hashrate of this machine (GPU kernel and CPU scanner).
Replaces the old hard-coded per-model estimates, which were never measured.
"""
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from ctypes import c_uint

from PySide6.QtCore import QThread, Signal

from app.miner.cpu_backend import CpuBackend, CpuBackendUnavailable
from app.miner.opencl_backend import OpenCLBackend, OpenCLContext

_HEADER = bytes(range(76))
BUILD_OPTIONS = "-cl-mad-enable -cl-no-signed-zeros -cl-fast-relaxed-math"


def build_search_kernel(ctx: OpenCLContext, device: dict, source: str):
    """Builds the fastest nonce-search kernel the device supports. Returns (kernel, variant name).
    NVIDIA gets the warp-shuffle Lyra2 kernel; its local size (work-group) must be a multiple of 32."""
    if "NVIDIA" in (device.get("vendor") or "").upper() and device.get("max_work_group_size", 0) >= 128:
        try:
            imad = tuple(device.get("cuda_cc", (0, 0)))[0] >= 12   # SM120 (RTX 50): CubeHash with IMAD adds
            ctx.build_program(source, options=BUILD_OPTIONS + " -DLYRA2_NV_SHFL" + (" -DLYRA2_NV_CUBE_IMAD" if imad else ""))
            kernel = ctx.get_kernel("search_lyra2v2_nv")
            ctx.set_arg_uint(kernel, 6, 1)   # cube_one: must be a run-time 1 (kernel arg persists across launches)
            return kernel, "NVIDIA warp-shuffle" + (" + IMAD CubeHash (SM120)" if imad else "")
        except Exception:
            pass
    ctx.build_program(source, options=BUILD_OPTIONS)
    return ctx.get_kernel("search_lyra2v2"), "generic"


def _kernel_source() -> str:
    candidates = [os.path.join(os.path.dirname(os.path.abspath(__file__)), "kernels", "lyra2v2.cl")]
    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
        candidates += [os.path.join(base, "app", "miner", "kernels", "lyra2v2.cl"),
                       os.path.join(getattr(sys, "_MEIPASS", base), "app", "miner", "kernels", "lyra2v2.cl")]
    for path in candidates:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
    raise FileNotFoundError("lyra2v2.cl")


def benchmark_gpu(device: dict, seconds: float = 3.0) -> float:
    """MH/s of one OpenCL device (device dict from OpenCLBackend.get_all_gpu_devices)."""
    ctx = OpenCLContext(device["platform_id"], device["id"])
    try:
        kernel, _ = build_search_kernel(ctx, device, _kernel_source())
        buf_header = ctx.create_buffer(76)
        buf_nonce = ctx.create_buffer(64)
        buf_count = ctx.create_buffer(4)
        ctx.write_buffer(buf_header, (c_uint * 19).from_buffer_copy(_HEADER), 76)
        wg = max(1, min(128, device.get("max_work_group_size", 128)))
        batch = (1 << 20) // wg * wg

        def launch(base):
            ctx.write_buffer(buf_count, (c_uint * 1)(0), 4)
            ctx.set_arg_mem(kernel, 0, buf_header)
            ctx.set_arg_uint(kernel, 1, base)
            ctx.set_arg_uint(kernel, 2, 0)   # impossible target: nothing is ever "found"
            ctx.set_arg_uint(kernel, 3, 0)
            ctx.set_arg_mem(kernel, 4, buf_nonce)
            ctx.set_arg_mem(kernel, 5, buf_count)
            ctx.run_kernel_1d(kernel, batch, wg)
            ctx.finish()

        launch(0)  # warm-up
        done = 0
        t0 = time.perf_counter()
        while time.perf_counter() - t0 < seconds:
            launch(done & 0xFFFFFFFF)
            done += batch
        return done / (time.perf_counter() - t0) / 1e6
    finally:
        ctx.release()


def benchmark_cpu(threads: int, seconds: float = 2.0) -> float:
    """Total MH/s of `threads` CPU threads."""
    chunk = 2000
    done = 0
    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=threads) as pool:
        while time.perf_counter() - t0 < seconds:
            futures = [pool.submit(CpuBackend.scan, _HEADER, i * chunk, chunk, 0, 0) for i in range(threads)]
            for f in futures:
                f.result()
            done += threads * chunk
    return done / (time.perf_counter() - t0) / 1e6


class BenchmarkWorker(QThread):
    """Runs the benchmark off the GUI thread. `result` = {"gpu_mhs": float|None, "cpu_mhs_per_thread": float|None, ...}"""
    result = Signal(dict)
    progress = Signal(str)

    def __init__(self, cpu_threads: int, gpu_index: int = 0, parent=None):
        super().__init__(parent)
        self.cpu_threads = max(1, cpu_threads)
        self.gpu_index = gpu_index

    def run(self):
        out = {"gpu_mhs": None, "gpu_name": None, "cpu_mhs_per_thread": None, "cpu_threads": self.cpu_threads}
        try:
            devices = OpenCLBackend.get_all_gpu_devices()
            device = next((d for d in devices if d["global_index"] == self.gpu_index), devices[0] if devices else None)
            if device:
                self.progress.emit(f"GPU ベンチマーク中: {device['name']} ...")
                out["gpu_mhs"] = round(benchmark_gpu(device), 2)
                out["gpu_name"] = device["name"]
        except Exception as e:
            out["gpu_error"] = str(e)
        try:
            CpuBackend.load()
            self.progress.emit(f"CPU ベンチマーク中 ({self.cpu_threads} スレッド) ...")
            out["cpu_mhs_per_thread"] = round(benchmark_cpu(self.cpu_threads) / self.cpu_threads, 3)
        except CpuBackendUnavailable as e:
            out["cpu_error"] = str(e)
        self.result.emit(out)
