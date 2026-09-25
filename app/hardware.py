import ctypes
import os
import sys
import platform
import psutil

try:
    import pynvml
    HAS_PYNVML = True
except ImportError:
    HAS_PYNVML = False

def is_admin() -> bool:
    """Check if the current process is running with Windows Administrator privileges."""
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False

class HardwareManager:
    def __init__(self):
        self.initialized = False
        self.has_nvml = False
        self.device_handle = None
        self.device_count = 0
        self.device_info = {
            "name": "N/A",
            "vram_gb": 0.0,
            "vram_free_gb": 0.0,
            "driver_version": "N/A",
            "cuda_version": "N/A",
            "compute_capability": (0, 0),
            "pwr_default_w": 0.0,
            "pwr_min_w": 0.0,
            "pwr_max_w": 0.0,
            "is_laptop": False,
            "is_rtx5080": False,
            "is_blackwell": False
        }
        self.cpu_info = {
            "name": platform.processor() or "AMD / Intel CPU",
            "logical_cores": os.cpu_count() or 4,
            "physical_cores": psutil.cpu_count(logical=False) or 2,
        }
        self.is_admin = is_admin()
        self.init_nvml()

    def init_nvml(self):
        if not HAS_PYNVML:
            return
        try:
            pynvml.nvmlInit()
            self.has_nvml = True
            self.device_count = pynvml.nvmlDeviceGetCount()
            if self.device_count > 0:
                self.device_handle = pynvml.nvmlDeviceGetHandleByIndex(0)
                self._inspect_device()
            self.initialized = True
        except Exception as e:
            print(f"[Hardware] NVML init failed: {e}")
            self.has_nvml = False

    def _inspect_device(self):
        h = self.device_handle
        try:
            self.device_info["name"] = pynvml.nvmlDeviceGetName(h)
        except Exception:
            pass

        try:
            mem = pynvml.nvmlDeviceGetMemoryInfo(h)
            self.device_info["vram_gb"] = round(mem.total / (1024 ** 3), 2)
            self.device_info["vram_free_gb"] = round(mem.free / (1024 ** 3), 2)
        except Exception:
            pass

        try:
            self.device_info["driver_version"] = pynvml.nvmlSystemGetDriverVersion()
            cuda_ver_code = pynvml.nvmlSystemGetCudaDriverVersion()
            # e.g. 13020 -> 13.2
            self.device_info["cuda_version"] = f"{cuda_ver_code // 1000}.{(cuda_ver_code % 1000) // 10}"
        except Exception:
            pass

        try:
            self.device_info["compute_capability"] = pynvml.nvmlDeviceGetCudaComputeCapability(h)
            major, minor = self.device_info["compute_capability"]
            if major >= 12:
                self.device_info["is_blackwell"] = True
        except Exception:
            pass

        try:
            pwr_limit = pynvml.nvmlDeviceGetPowerManagementLimit(h) / 1000.0
            pwr_range = [x / 1000.0 for x in pynvml.nvmlDeviceGetPowerManagementLimitConstraints(h)]
            self.device_info["pwr_default_w"] = pwr_limit
            self.device_info["pwr_min_w"] = pwr_range[0]
            self.device_info["pwr_max_w"] = pwr_range[1]
        except Exception:
            pass

        name_lower = self.device_info["name"].lower()
        if "5080" in name_lower:
            self.device_info["is_rtx5080"] = True
        if "laptop" in name_lower or "mobile" in name_lower or "max-q" in name_lower:
            self.device_info["is_laptop"] = True

    def get_live_metrics(self) -> dict:
        """Returns instantaneous GPU and CPU telemetry."""
        cpu_pct = 0
        try:
            cpu_pct = int(psutil.cpu_percent(interval=None))
        except Exception:
            cpu_pct = 0

        if not self.has_nvml or not self.device_handle:
            return {
                "temp_c": 0,
                "fan_pct": 0,
                "power_w": 0.0,
                "gpu_util_pct": 0,
                "mem_util_pct": 0,
                "clock_sm_mhz": 0,
                "clock_mem_mhz": 0,
                "vram_used_gb": 0.0,
                "vram_total_gb": 0.0,
                "cpu_util_pct": cpu_pct
            }

        h = self.device_handle
        metrics = {}
        try:
            metrics["temp_c"] = pynvml.nvmlDeviceGetTemperature(h, pynvml.NVML_TEMPERATURE_GPU)
        except Exception:
            metrics["temp_c"] = 0

        try:
            metrics["fan_pct"] = pynvml.nvmlDeviceGetFanSpeed(h)
        except Exception:
            metrics["fan_pct"] = 0

        try:
            metrics["power_w"] = round(pynvml.nvmlDeviceGetPowerUsage(h) / 1000.0, 1)
        except Exception:
            metrics["power_w"] = 0.0

        try:
            util = pynvml.nvmlDeviceGetUtilizationRates(h)
            metrics["gpu_util_pct"] = util.gpu
            metrics["mem_util_pct"] = util.memory
        except Exception:
            metrics["gpu_util_pct"] = 0
            metrics["mem_util_pct"] = 0

        try:
            metrics["clock_sm_mhz"] = pynvml.nvmlDeviceGetClockInfo(h, pynvml.NVML_CLOCK_SM)
            metrics["clock_mem_mhz"] = pynvml.nvmlDeviceGetClockInfo(h, pynvml.NVML_CLOCK_MEM)
        except Exception:
            metrics["clock_sm_mhz"] = 0
            metrics["clock_mem_mhz"] = 0

        try:
            mem = pynvml.nvmlDeviceGetMemoryInfo(h)
            metrics["vram_used_gb"] = round((mem.total - mem.free) / (1024 ** 3), 2)
            metrics["vram_total_gb"] = round(mem.total / (1024 ** 3), 2)
        except Exception:
            metrics["vram_used_gb"] = 0.0
            metrics["vram_total_gb"] = 0.0

        try:
            metrics["cpu_util_pct"] = int(psutil.cpu_percent(interval=None))
        except Exception:
            metrics["cpu_util_pct"] = 0

        return metrics

    def get_mode_recommendation(self) -> dict:
        """
        Analyzes the detected hardware and returns optimized profiles.
        """
        info = self.device_info
        is_5080 = info["is_rtx5080"]
        is_laptop = info["is_laptop"]
        min_pwr = info["pwr_min_w"] or 250.0
        max_pwr = info["pwr_max_w"] or 360.0

        cpu_phys = self.cpu_info["physical_cores"]
        cpu_log = self.cpu_info["logical_cores"]

        # Dynamic CPU thread targets based on detected topology
        cpu_threads_eco = cpu_phys  # 16T: Physical cores only (Peak L3 Cache efficiency & Hash/W)
        cpu_threads_perf = max(1, cpu_log - 2) if cpu_log > 4 else cpu_log  # 30T: Max threads leaving 2 for OS & GPU driver
        cpu_threads_quiet = max(1, cpu_phys // 2)  # 8T: 25% CPU load, totally silent

        modes = {
            "eco": {
                "name": "🍃 電力効率モード (Eco / Sweet Spot)",
                "target_pwr_w": min_pwr if min_pwr > 0 else 250.0,
                "intensity": 21,
                "cpu_threads": cpu_threads_eco,
                "badge": "推奨 (低発熱・高Hash/W)",
                "description": f"GPU: {min_pwr:.0f}W (電圧抑制) / CPU: {cpu_threads_eco}スレッド (物理コア優先)。SMT競合を回避し、マシン全体の電力効率を最大化します。",
                "est_hashrate": "GPU ~172 + CPU ~11 => 計 ~183 MH/s",
                "est_efficiency": "最高ワットパフォーマンス"
            },
            "perf": {
                "name": "⚡ 最大計算力モード (Max Hashrate)",
                "target_pwr_w": max_pwr if max_pwr > 0 else 360.0,
                "intensity": 24,
                "cpu_threads": cpu_threads_perf,
                "badge": "最大性能 (360W + 30T フルパワー)",
                "description": f"GPU: 360W定格全開 / CPU: {cpu_threads_perf}スレッド (OS用2スレッド確保)。GPUとCPUの全能力を解き放つ極限ハッシュレート構成です。",
                "est_hashrate": "GPU ~218 + CPU ~20 => 計 ~238 MH/s",
                "est_efficiency": "最大採掘量最優先"
            },
            "quiet": {
                "name": "☕ ながらマイニングモード (Quiet / Daily)",
                "target_pwr_w": min_pwr if min_pwr > 0 else 200.0,
                "intensity": 16,
                "cpu_threads": cpu_threads_quiet,
                "badge": "静音・軽作業と両立",
                "description": f"GPU使用率30〜40% / CPU: {cpu_threads_quiet}スレッド (25%低負荷)。日常のPC操作や動画視聴を一切妨げずに裏で静かに採掘します。",
                "est_hashrate": "GPU ~88 + CPU ~5 => 計 ~93 MH/s",
                "est_efficiency": "低負荷・静音重視"
            }
        }

        # Auto-recommendation logic
        if is_laptop:
            recommended_mode = "quiet"
            rationale = "【ノートPC検出】排熱とバッテリー安全性を考慮し、「ながらマイニング（低負荷）」を自動推奨します。"
        elif is_5080:
            recommended_mode = "eco"
            rationale = (
                f"【RTX 5080 & {cpu_log}スレッドCPU 最適化検知】\n"
                f"・GPU: 超巨大L2キャッシュにより250Wでも高いハッシュレートを維持（定格360Wは発熱過大）。\n"
                f"・CPU: 物理{cpu_phys}コアに絞ることでSMTのL3キャッシュ競合を防ぎ、最高効率を発揮します。\n"
                f"⇒ 最も電気代対効果が高い「🍃 電力効率モード (GPU 250W + CPU {cpu_threads_eco}T)」を自動推奨します。"
            )
        else:
            recommended_mode = "eco"
            rationale = "標準的なデスクトップハードウェアを検知しました。バランスの良い「電力効率モード」を推奨します。"

        return {
            "recommended_key": recommended_mode,
            "rationale": rationale,
            "modes": modes
        }

    def apply_power_limit(self, target_w: float) -> tuple[bool, str]:
        """
        Applies power limit if running with administrator privileges.
        """
        if not self.has_nvml or not self.device_handle:
            return False, "NVMLが利用できません"
        if not self.is_admin:
            return False, "管理者権限が必要です。Intensity（スレッド強度）のみで負荷制御します。"

        min_w = self.device_info["pwr_min_w"]
        max_w = self.device_info["pwr_max_w"]
        target_w = max(min_w, min(max_w, target_w))
        target_mw = int(target_w * 1000)

        try:
            pynvml.nvmlDeviceSetPowerManagementLimit(self.device_handle, target_mw)
            return True, f"Power Limit を {target_w:.0f}W に設定しました。"
        except pynvml.NVMLError_NoPermission:
            return False, "権限不足: Windowsの管理者権限で実行されていません。"
        except Exception as e:
            return False, f"Power Limit 設定エラー: {e}"

    def shutdown(self):
        if self.has_nvml:
            try:
                pynvml.nvmlShutdown()
            except Exception:
                pass
