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

GPU_BENCHMARKS = [
    # (name_keyword, eco_hr, perf_hr, quiet_hr)
    ("5090", 250.0, 320.0, 130.0),
    ("5080", 172.0, 218.0, 88.0),
    ("5070 ti", 125.0, 160.0, 65.0),
    ("5070", 105.0, 135.0, 55.0),
    ("4090", 170.0, 215.0, 85.0),
    ("4080 super", 125.0, 155.0, 62.0),
    ("4080", 120.0, 150.0, 60.0),
    ("4070 ti super", 100.0, 130.0, 50.0),
    ("4070 ti", 95.0, 120.0, 48.0),
    ("4070 super", 85.0, 110.0, 44.0),
    ("4070", 75.0, 95.0, 38.0),
    ("4060 ti", 55.0, 70.0, 28.0),
    ("4060", 42.0, 54.0, 22.0),
    ("3090 ti", 115.0, 140.0, 58.0),
    ("3090", 105.0, 130.0, 52.0),
    ("3080 ti", 100.0, 125.0, 50.0),
    ("3080", 90.0, 110.0, 45.0),
    ("3070 ti", 70.0, 85.0, 35.0),
    ("3070", 62.0, 76.0, 31.0),
    ("3060 ti", 55.0, 68.0, 28.0),
    ("3060", 40.0, 50.0, 20.0),
    ("3050", 25.0, 32.0, 13.0),
    ("2080 ti", 65.0, 80.0, 32.0),
    ("2080 super", 55.0, 68.0, 28.0),
    ("2080", 50.0, 62.0, 25.0),
    ("2070 super", 48.0, 58.0, 24.0),
    ("2070", 42.0, 52.0, 21.0),
    ("2060 super", 40.0, 49.0, 20.0),
    ("2060", 35.0, 43.0, 18.0),
    ("1660 ti", 28.0, 35.0, 14.0),
    ("1660 super", 27.0, 34.0, 14.0),
    ("1660", 24.0, 30.0, 12.0),
    ("1650", 16.0, 20.0, 8.0),
    ("1080 ti", 58.0, 72.0, 29.0),
    ("1080", 44.0, 54.0, 22.0),
    ("1070 ti", 42.0, 52.0, 21.0),
    ("1070", 35.0, 44.0, 18.0),
    ("1060", 22.0, 28.0, 11.0),
    ("1050 ti", 12.0, 15.0, 6.0),
]

def get_arch_name(major: int, minor: int) -> str:
    if major >= 12:
        return "Blackwell"
    elif major == 8 and minor >= 9:
        return "Ada Lovelace"
    elif major == 8:
        return "Ampere"
    elif major == 7 and minor == 5:
        return "Turing"
    elif major == 7:
        return "Volta"
    elif major == 6:
        return "Pascal"
    elif major == 5:
        return "Maxwell"
    elif major > 0:
        return f"CUDA (sm_{major}{minor})"
    else:
        return "NVIDIA GPU"

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
            "short_name": "GPU",
            "arch_name": "NVIDIA GPU",
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
            self.device_info["arch_name"] = get_arch_name(major, minor)
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

        name = self.device_info["name"]
        name_lower = name.lower()
        if "5080" in name_lower:
            self.device_info["is_rtx5080"] = True
        if "laptop" in name_lower or "mobile" in name_lower or "max-q" in name_lower:
            self.device_info["is_laptop"] = True

        # Short name formatting
        short = name.replace("NVIDIA ", "").replace("GeForce ", "").strip()
        self.device_info["short_name"] = short or "GPU"

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
        Analyzes the detected hardware (any NVIDIA GPU + CPU) and returns optimized profiles.
        """
        info = self.device_info
        has_gpu = self.has_nvml and self.device_count > 0
        name = info["name"]
        short_name = info["short_name"]
        compute_cap = info.get("compute_capability", (0, 0))
        arch_name = get_arch_name(compute_cap[0], compute_cap[1])
        is_laptop = info.get("is_laptop", False)

        pwr_def = info["pwr_default_w"]
        pwr_min = info["pwr_min_w"]
        pwr_max = info["pwr_max_w"]

        # 1. Estimate base GPU hashrates (Eco, Perf, Quiet)
        name_lower = name.lower()
        match = None
        for kw, eco, perf, quiet in GPU_BENCHMARKS:
            if kw in name_lower:
                match = (eco, perf, quiet)
                break

        if match:
            eco_gpu_hr, perf_gpu_hr, quiet_gpu_hr = match
        elif has_gpu:
            major, minor = compute_cap
            eff = 0.58 if major >= 12 else (0.45 if major >= 8 and minor >= 9 else (0.30 if major >= 8 else 0.22))
            base_pwr = pwr_def if pwr_def > 0 else 180.0
            perf_gpu_hr = round(base_pwr * eff, 1)
            eco_gpu_hr = round(perf_gpu_hr * 0.78, 1)
            quiet_gpu_hr = round(perf_gpu_hr * 0.40, 1)
        else:
            eco_gpu_hr, perf_gpu_hr, quiet_gpu_hr = 0.0, 0.0, 0.0

        if is_laptop:
            eco_gpu_hr = round(eco_gpu_hr * 0.80, 1)
            perf_gpu_hr = round(perf_gpu_hr * 0.80, 1)
            quiet_gpu_hr = round(quiet_gpu_hr * 0.80, 1)

        # 2. Determine power limits in Watts
        if pwr_def > 0:
            c_min = pwr_min if pwr_min > 0 else round(pwr_def * 0.65)
            c_max = pwr_max if pwr_max > 0 else pwr_def
            pwr_eco = max(c_min, round(pwr_def * 0.70))
            pwr_perf = c_max
            pwr_quiet = max(c_min, round(pwr_def * 0.50))
        else:
            pwr_eco = 150.0
            pwr_perf = 220.0
            pwr_quiet = 100.0

        # Intensity
        major = compute_cap[0]
        intensity_eco = 21 if major >= 8 else 20
        intensity_perf = 24 if major >= 8 else 22
        intensity_quiet = 16 if major >= 8 else 15

        # CPU threads & hashrate
        cpu_phys = self.cpu_info["physical_cores"]
        cpu_log = self.cpu_info["logical_cores"]
        cpu_threads_eco = cpu_phys
        cpu_threads_perf = max(1, cpu_log - 2) if cpu_log > 4 else cpu_log
        cpu_threads_quiet = max(1, cpu_phys // 2)

        cpu_hr_eco = round(cpu_threads_eco * 0.68, 1)
        cpu_hr_perf = round(cpu_threads_perf * 0.68, 1)
        cpu_hr_quiet = round(cpu_threads_quiet * 0.68, 1)

        modes = {
            "eco": {
                "name": "🍃 電力効率モード (Eco / Sweet Spot)",
                "target_pwr_w": pwr_eco,
                "est_gpu_hr": eco_gpu_hr,
                "intensity": intensity_eco,
                "cpu_threads": cpu_threads_eco,
                "badge": "推奨 (低発熱・高Hash/W)",
                "description": f"GPU: {pwr_eco:.0f}W (電圧抑制) / CPU: {cpu_threads_eco}スレッド (物理コア優先)。SMT競合を回避し、マシン全体の電力効率を最大化します。",
                "est_hashrate": f"GPU ~{eco_gpu_hr:.0f} + CPU ~{cpu_hr_eco:.0f} => 計 ~{eco_gpu_hr + cpu_hr_eco:.0f} MH/s" if has_gpu else f"CPU ~{cpu_hr_eco:.0f} MH/s",
                "est_efficiency": "最高ワットパフォーマンス"
            },
            "perf": {
                "name": "⚡ 最大計算力モード (Max Hashrate)",
                "target_pwr_w": pwr_perf,
                "est_gpu_hr": perf_gpu_hr,
                "intensity": intensity_perf,
                "cpu_threads": cpu_threads_perf,
                "badge": f"最大性能 ({pwr_perf:.0f}W + {cpu_threads_perf}T フルパワー)",
                "description": f"GPU: {pwr_perf:.0f}W定格全開 / CPU: {cpu_threads_perf}スレッド (OS用2スレッド確保)。GPUとCPUの全能力を解き放つ極限ハッシュレート構成です。",
                "est_hashrate": f"GPU ~{perf_gpu_hr:.0f} + CPU ~{cpu_hr_perf:.0f} => 計 ~{perf_gpu_hr + cpu_hr_perf:.0f} MH/s" if has_gpu else f"CPU ~{cpu_hr_perf:.0f} MH/s",
                "est_efficiency": "最大採掘量最優先"
            },
            "quiet": {
                "name": "☕ ながらマイニングモード (Quiet / Daily)",
                "target_pwr_w": pwr_quiet,
                "est_gpu_hr": quiet_gpu_hr,
                "intensity": intensity_quiet,
                "cpu_threads": cpu_threads_quiet,
                "badge": "静音・軽作業と両立",
                "description": f"GPU使用率30〜40% / CPU: {cpu_threads_quiet}スレッド (25%低負荷)。日常のPC操作や動画視聴を一切妨げずに裏で静かに採掘します。",
                "est_hashrate": f"GPU ~{quiet_gpu_hr:.0f} + CPU ~{cpu_hr_quiet:.0f} => 計 ~{quiet_gpu_hr + cpu_hr_quiet:.0f} MH/s" if has_gpu else f"CPU ~{cpu_hr_quiet:.0f} MH/s",
                "est_efficiency": "低負荷・静音重視"
            }
        }

        # Auto-recommendation logic
        if is_laptop:
            recommended_mode = "quiet"
            rationale = (
                f"【ノートPC ({short_name}) 検出】\n"
                f"・排熱・バッテリー・静音性を考慮し、「☕ ながらマイニング（低負荷）」を自動推奨します。\n"
                f"・GPU: 低負荷スレッド (Intensity {intensity_quiet}) / CPU: {cpu_threads_quiet}スレッドで熱を抑制。"
            )
        elif has_gpu:
            recommended_mode = "eco"
            rationale = (
                f"【{short_name} ({arch_name}) & {cpu_log}スレッドCPU 最適化検知】\n"
                f"・GPU: 電力効率スイートスポット ({pwr_eco:.0f}W / 定格 {pwr_def:.0f}W) を適用して発熱と電気代を大幅削減。\n"
                f"・CPU: 物理{cpu_phys}コアに絞ることでキャッシュ競合を防ぎ、最高効率を発揮します。\n"
                f"⇒ 最も電気代対効果が高い「🍃 電力効率モード (GPU {pwr_eco:.0f}W + CPU {cpu_threads_eco}T)」を自動推奨します。"
            )
        else:
            recommended_mode = "eco"
            rationale = (
                f"【CPUマイニング最適化検知】\n"
                f"・NVIDIA GPU未検出のため、多コアCPU ({cpu_log}スレッド) に特化した最適化プロファイルを提案します。\n"
                f"・物理{cpu_phys}コアを専有することで、日常動作を阻害せず安定したマイニングが可能です。"
            )

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
