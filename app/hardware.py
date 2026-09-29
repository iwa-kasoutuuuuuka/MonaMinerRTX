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

AMD_DEFAULT_TDP = [
    ("7900 xtx", 355.0, 250.0),
    ("7900 xt", 315.0, 220.0),
    ("7900 gre", 260.0, 180.0),
    ("7800 xt", 263.0, 180.0),
    ("7700 xt", 245.0, 170.0),
    ("7600 xt", 190.0, 130.0),
    ("7600", 165.0, 115.0),
    ("6950 xt", 335.0, 235.0),
    ("6900 xt", 300.0, 210.0),
    ("6800 xt", 300.0, 210.0),
    ("6800", 250.0, 175.0),
    ("6750 xt", 250.0, 175.0),
    ("6700 xt", 230.0, 160.0),
    ("6650 xt", 180.0, 125.0),
    ("6600 xt", 160.0, 110.0),
    ("6600", 132.0, 95.0),
    ("5700 xt", 225.0, 155.0),
    ("5700", 180.0, 125.0),
    ("5600 xt", 150.0, 105.0),
    ("radeon vii", 300.0, 210.0),
    ("vega 64", 295.0, 200.0),
    ("vega 56", 210.0, 145.0),
    ("rx 590", 225.0, 150.0),
    ("rx 580", 185.0, 130.0),
    ("rx 570", 150.0, 105.0),
    ("rx 480", 150.0, 105.0),
    ("rx 470", 120.0, 85.0),
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

def get_amd_arch_name(name: str) -> str:
    n = name.upper()
    if any(k in n for k in ['7900', '7800', '7700', '7600']):
        return "RDNA 3"
    elif any(k in n for k in ['6950', '6900', '6800', '6750', '6700', '6650', '6600', '6500', '6400']):
        return "RDNA 2"
    elif any(k in n for k in ['5700', '5600', '5500', '5300']):
        return "RDNA 1"
    elif 'VEGA' in n or 'RADEON VII' in n:
        return "GCN 5th (Vega)"
    elif any(k in n for k in ['590', '580', '570', '560', '550', '480', '470', '460']):
        return "GCN 4th (Polaris)"
    return "AMD Radeon (OpenCL)"

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
        self.has_gpu = False
        self.device_handle = None
        self.device_count = 0
        self.device_info = {
            "vendor": "UNKNOWN", # "NVIDIA", "AMD", "INTEL", "NONE"
            "name": "N/A",
            "short_name": "GPU",
            "arch_name": "GPU",
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
            "is_blackwell": False,
            "is_amd": False,
            "is_nvidia": False,
        }
        self.cpu_info = {
            "name": platform.processor() or "AMD / Intel CPU",
            "logical_cores": os.cpu_count() or 4,
            "physical_cores": psutil.cpu_count(logical=False) or 2,
        }
        self.is_admin = is_admin()
        self._limit_before_mining_mw = None  # power limit to restore once mining stops
        # Real hashrates from the built-in benchmark (app/miner/benchmark.py); None = not measured yet
        self.measured = {"gpu_mhs": None, "cpu_mhs_per_thread": None}
        self.init_nvml()

    def init_nvml(self):
        if HAS_PYNVML:
            try:
                pynvml.nvmlInit()
                self.has_nvml = True
                self.device_count = pynvml.nvmlDeviceGetCount()
                if self.device_count > 0:
                    self.has_gpu = True
                    self.device_info["vendor"] = "NVIDIA"
                    self.device_info["is_nvidia"] = True
                    self.device_handle = pynvml.nvmlDeviceGetHandleByIndex(0)
                    self._inspect_device()
                    self.initialized = True
                    return
            except Exception as e:
                print(f"[Hardware] NVML init failed: {e}")
                self.has_nvml = False

        # Fallback for AMD Radeon or systems without NVML
        self._inspect_fallback_gpus()
        self.initialized = True

    def _inspect_fallback_gpus(self):
        """Detects AMD Radeon or generic display adapters via Windows CIM/WMI."""
        if sys.platform != "win32":
            return
        try:
            import subprocess
            import json
            cmd = ['powershell', '-NoProfile', '-Command',
                   'Get-CimInstance Win32_VideoController | Select-Object Name, AdapterRAM, DriverVersion | ConvertTo-Json']
            out = subprocess.check_output(cmd, text=True, timeout=6)
            adapters = json.loads(out)
            if isinstance(adapters, dict):
                adapters = [adapters]

            for a in adapters:
                name = a.get("Name", "")
                name_upper = name.upper()
                if "RADEON" in name_upper or "AMD" in name_upper or "ADVANCED MICRO DEVICES" in name_upper:
                    self.has_gpu = True
                    self.device_count = 1
                    self.device_info["vendor"] = "AMD"
                    self.device_info["is_amd"] = True
                    self.device_info["name"] = name
                    self.device_info["driver_version"] = str(a.get("DriverVersion", "N/A"))
                    ram_bytes = a.get("AdapterRAM", 0) or 0
                    self.device_info["vram_gb"] = round(ram_bytes / (1024 ** 3), 1) if ram_bytes > 0 else 8.0
                    self.device_info["arch_name"] = get_amd_arch_name(name)

                    # Short name
                    short = name.replace("AMD ", "").replace("Radeon ", "").strip()
                    self.device_info["short_name"] = short or "Radeon GPU"

                    # Estimate TDP constraints
                    name_lower = name.lower()
                    match_tdp = None
                    for kw, def_w, min_w in AMD_DEFAULT_TDP:
                        if kw in name_lower:
                            match_tdp = (def_w, min_w)
                            break
                    if match_tdp:
                        self.device_info["pwr_default_w"] = match_tdp[0]
                        self.device_info["pwr_min_w"] = match_tdp[1]
                        self.device_info["pwr_max_w"] = match_tdp[0]
                    else:
                        self.device_info["pwr_default_w"] = 220.0
                        self.device_info["pwr_min_w"] = 150.0
                        self.device_info["pwr_max_w"] = 250.0

                    if "laptop" in name_lower or "mobile" in name_lower:
                        self.device_info["is_laptop"] = True
                    break
        except Exception as e:
            print(f"[Hardware] Fallback AMD inspection: {e}")

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
            # The *default* limit: the currently applied one may still be a leftover of an earlier run.
            try:
                pwr_limit = pynvml.nvmlDeviceGetPowerManagementDefaultLimit(h) / 1000.0
            except Exception:
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
        has_gpu = self.has_gpu or (self.has_nvml and self.device_count > 0)
        name = info["name"]
        short_name = info["short_name"]
        is_amd = info.get("is_amd", False)
        compute_cap = info.get("compute_capability", (0, 0))
        if is_amd:
            arch_name = info.get("arch_name", "AMD Radeon")
        else:
            arch_name = get_arch_name(compute_cap[0], compute_cap[1])
        is_laptop = info.get("is_laptop", False)

        pwr_def = info["pwr_default_w"]
        pwr_min = info["pwr_min_w"]
        pwr_max = info["pwr_max_w"]

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

        # Hashrate estimates come from the benchmark only. Power-limited profiles are scaled by their
        # power ratio, a rough rule of thumb (not measured).
        gpu_measured = self.measured.get("gpu_mhs") if has_gpu else None
        if gpu_measured:
            ref_pwr = pwr_perf if pwr_perf > 0 else 1.0
            perf_gpu_hr = round(gpu_measured, 1)
            eco_gpu_hr = round(gpu_measured * min(1.0, pwr_eco / ref_pwr), 1)
            quiet_gpu_hr = round(gpu_measured * min(1.0, pwr_quiet / ref_pwr), 1)
        else:
            eco_gpu_hr = perf_gpu_hr = quiet_gpu_hr = 0.0

        # Intensity
        major = compute_cap[0]
        if is_amd:
            intensity_eco = 20
            intensity_perf = 23
            intensity_quiet = 15
        else:
            intensity_eco = 21 if major >= 8 else 20
            intensity_perf = 24 if major >= 8 else 22
            intensity_quiet = 16 if major >= 8 else 15

        # CPU threads & hashrate
        cpu_phys = self.cpu_info["physical_cores"]
        cpu_log = self.cpu_info["logical_cores"]
        cpu_threads_eco = cpu_phys
        cpu_threads_perf = max(1, cpu_log - 2) if cpu_log > 4 else cpu_log
        cpu_threads_quiet = max(1, cpu_phys // 2)

        per_thread = self.measured.get("cpu_mhs_per_thread") or 0.0
        cpu_hr_eco = round(cpu_threads_eco * per_thread, 2)
        cpu_hr_perf = round(cpu_threads_perf * per_thread, 2)
        cpu_hr_quiet = round(cpu_threads_quiet * per_thread, 2)

        def est_text(gpu_hr: float, cpu_hr: float) -> str:
            if (has_gpu and gpu_hr <= 0) or cpu_hr <= 0:
                return "未測定 (詳細設定の「ベンチマーク」で計測)"
            if has_gpu:
                return f"GPU ~{gpu_hr:.0f} + CPU ~{cpu_hr:.1f} => 計 ~{gpu_hr + cpu_hr:.0f} MH/s (実測ベース)"
            return f"CPU ~{cpu_hr:.1f} MH/s (実測ベース)"

        modes = {
            "eco": {
                "name": "🍃 電力効率モード (Eco / Sweet Spot)",
                "target_pwr_w": pwr_eco,
                "est_gpu_hr": eco_gpu_hr,
                "intensity": intensity_eco,
                "cpu_threads": cpu_threads_eco,
                "badge": "推奨 (低発熱・高Hash/W)",
                "description": f"GPU: {pwr_eco:.0f}W (電圧抑制) / CPU: {cpu_threads_eco}スレッド (物理コア優先)。SMT競合を回避し、マシン全体の電力効率を最大化します。",
                "est_hashrate": est_text(eco_gpu_hr, cpu_hr_eco),
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
                "est_hashrate": est_text(perf_gpu_hr, cpu_hr_perf),
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
                "est_hashrate": est_text(quiet_gpu_hr, cpu_hr_quiet),
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
        elif is_amd:
            recommended_mode = "eco"
            rationale = (
                f"【AMD Radeon ({short_name} - {arch_name}) & {cpu_log}スレッドCPU 最適化検知】\n"
                f"・GPU: OpenCL 最適化プロファイル ({pwr_eco:.0f}W / 推定定格 {pwr_def:.0f}W) を適用。\n"
                f"・CPU: 物理{cpu_phys}コアに絞ることでキャッシュ競合を防ぎ、最高効率を発揮します。\n"
                f"⇒ 最も電気代対効果が高い「🍃 電力効率モード (GPU {pwr_eco:.0f}W + CPU {cpu_threads_eco}T)」を自動推奨します。"
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
                f"・GPU未検出のため、多コアCPU ({cpu_log}スレッド) に特化した最適化プロファイルを提案します。\n"
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
            if self.device_info.get("is_amd", False):
                return False, "AMD Radeon環境: 電力制限制御はAMD Software (Adrenalin) またはIntensity強度で調整してください。"
            return False, "NVMLが利用できません"
        if not self.is_admin:
            return False, "管理者権限が必要です。Intensity（スレッド強度）のみで負荷制御します。"

        min_w = self.device_info["pwr_min_w"]
        max_w = self.device_info["pwr_max_w"]
        target_w = max(min_w, min(max_w, target_w))
        target_mw = int(target_w * 1000)

        try:
            if self._limit_before_mining_mw is None:
                self._limit_before_mining_mw = pynvml.nvmlDeviceGetPowerManagementLimit(self.device_handle)
            pynvml.nvmlDeviceSetPowerManagementLimit(self.device_handle, target_mw)
            return True, f"Power Limit を {target_w:.0f}W に設定しました。"
        except pynvml.NVMLError_NoPermission:
            return False, "権限不足: Windowsの管理者権限で実行されていません。"
        except Exception as e:
            return False, f"Power Limit 設定エラー: {e}"

    def set_measured(self, gpu_mhs=None, cpu_mhs_per_thread=None):
        self.measured = {"gpu_mhs": gpu_mhs or None, "cpu_mhs_per_thread": cpu_mhs_per_thread or None}

    def restore_power_limit(self) -> tuple[bool, str]:
        """Puts the GPU power limit back to what it was before mining started (no-op if never changed)."""
        if self._limit_before_mining_mw is None or not self.has_nvml or not self.device_handle:
            return True, ""
        original_mw = self._limit_before_mining_mw
        self._limit_before_mining_mw = None
        try:
            pynvml.nvmlDeviceSetPowerManagementLimit(self.device_handle, original_mw)
            return True, f"Power Limit を元の {original_mw / 1000:.0f}W に戻しました。"
        except Exception as e:
            return False, f"Power Limit の復元に失敗しました: {e}"

    def shutdown(self):
        if self.has_nvml:
            try:
                pynvml.nvmlShutdown()
            except Exception:
                pass
