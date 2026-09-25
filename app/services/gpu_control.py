"""
GPU hardware monitoring and management using direct ctypes binding to nvml.dll.
Zero external pip dependencies required.
Supports reading and adjusting Power Limits, Fan Speeds, and Temperature Targets.
"""
import ctypes
import os
import sys
from typing import Dict, Any, List, Optional, Tuple

# NVML return codes
NVML_SUCCESS = 0
NVML_ERROR_UNINITIALIZED = 1
NVML_ERROR_INVALID_ARGUMENT = 2
NVML_ERROR_NOT_SUPPORTED = 3
NVML_ERROR_NO_PERMISSION = 4
NVML_ERROR_ALREADY_INITIALIZED = 5
NVML_ERROR_NOT_FOUND = 6
NVML_ERROR_INSUFFICIENT_SIZE = 7
NVML_ERROR_INSUFFICIENT_POWER = 8
NVML_ERROR_DRIVER_NOT_LOADED = 9
NVML_ERROR_TIMEOUT = 10
NVML_ERROR_IRQ_ISSUE = 11
NVML_ERROR_LIBRARY_NOT_FOUND = 12
NVML_ERROR_FUNCTION_NOT_FOUND = 13
NVML_ERROR_CORRUPTED_INFOROM = 14
NVML_ERROR_GPU_IS_LOST = 15
NVML_ERROR_RESET_REQUIRED = 16
NVML_ERROR_OPERATING_SYSTEM = 17
NVML_ERROR_LIB_RM_VERSION_MISMATCH = 18
NVML_ERROR_IN_USE = 19
NVML_ERROR_MEMORY = 20
NVML_ERROR_NO_DATA = 21
NVML_ERROR_VGPU_ECC_NOT_SUPPORTED = 22
NVML_ERROR_INSUFFICIENT_RESOURCES = 23
NVML_ERROR_UNKNOWN = 999


class GpuHardwareController:
    def __init__(self):
        self._nvml = None
        self._initialized = False
        self._device_count = 0
        self._init_nvml()

    def _init_nvml(self):
        if sys.platform != "win32":
            return
        
        # Possible DLL locations on Windows
        dll_candidates = [
            "nvml.dll",
            os.path.join(os.environ.get("SystemRoot", "C:\\Windows"), "System32", "nvml.dll"),
            os.path.join(os.environ.get("ProgramFiles", "C:\\Program Files"), "NVIDIA Corporation", "NVSMI", "nvml.dll")
        ]

        for path in dll_candidates:
            try:
                self._nvml = ctypes.CDLL(path)
                if self._nvml.nvmlInit_v2() == NVML_SUCCESS:
                    self._initialized = True
                    count = ctypes.c_uint()
                    if self._nvml.nvmlDeviceGetCount_v2(ctypes.byref(count)) == NVML_SUCCESS:
                        self._device_count = count.value
                    break
            except Exception:
                continue

    @property
    def is_available(self) -> bool:
        return self._initialized and self._device_count > 0

    @property
    def device_count(self) -> int:
        return self._device_count

    def get_device_info(self, index: int) -> Dict[str, Any]:
        """
        Retrieves telemetry for GPU at index.
        """
        if not self.is_available or index >= self._device_count:
            return {}

        handle = ctypes.c_void_p()
        if self._nvml.nvmlDeviceGetHandleByIndex_v2(ctypes.c_uint(index), ctypes.byref(handle)) != NVML_SUCCESS:
            return {}

        # Name
        name_buf = ctypes.create_string_buffer(64)
        self._nvml.nvmlDeviceGetName(handle, name_buf, ctypes.c_uint(64))
        name = name_buf.value.decode("utf-8", errors="ignore")

        # Temperature
        temp = ctypes.c_uint(0)
        self._nvml.nvmlDeviceGetTemperature(handle, ctypes.c_uint(0), ctypes.byref(temp))

        # Fan speed
        fan = ctypes.c_uint(0)
        self._nvml.nvmlDeviceGetFanSpeed(handle, ctypes.byref(fan))

        # Power usage (mW -> W)
        power_mw = ctypes.c_uint(0)
        self._nvml.nvmlDeviceGetPowerUsage(handle, ctypes.byref(power_mw))
        power_w = power_mw.value / 1000.0 if power_mw.value > 0 else 0.0

        # Power limit constraints (mW -> W)
        min_p = ctypes.c_uint(0)
        max_p = ctypes.c_uint(0)
        cur_limit = ctypes.c_uint(0)
        self._nvml.nvmlDeviceGetPowerManagementLimitConstraints(handle, ctypes.byref(min_p), ctypes.byref(max_p))
        self._nvml.nvmlDeviceGetPowerManagementLimit(handle, ctypes.byref(cur_limit))

        return {
            "index": index,
            "name": name,
            "temp_c": temp.value,
            "fan_percent": fan.value,
            "power_w": round(power_w, 1),
            "cur_power_limit_w": round(cur_limit.value / 1000.0, 1) if cur_limit.value > 0 else None,
            "min_power_limit_w": round(min_p.value / 1000.0, 1) if min_p.value > 0 else None,
            "max_power_limit_w": round(max_p.value / 1000.0, 1) if max_p.value > 0 else None,
        }

    def set_power_limit(self, index: int, watts: float) -> Tuple[bool, str]:
        """
        Sets power management limit in Watts. Requires Administrator privileges.
        """
        if not self.is_available or index >= self._device_count:
            return False, "NVMLが利用できません"

        handle = ctypes.c_void_p()
        if self._nvml.nvmlDeviceGetHandleByIndex_v2(ctypes.c_uint(index), ctypes.byref(handle)) != NVML_SUCCESS:
            return False, "デバイスハンドル取得失敗"

        mw = int(watts * 1000)
        ret = self._nvml.nvmlDeviceSetPowerManagementLimit(handle, ctypes.c_uint(mw))
        if ret == NVML_SUCCESS:
            return True, f"電力リミットを {watts}W に設定しました"
        elif ret == NVML_ERROR_NO_PERMISSION:
            return False, "管理者権限が必要です。管理者としてアプリを再起動してください。"
        else:
            return False, f"設定に失敗しました (エラーコード: {ret})"

    def set_fan_speed(self, index: int, percent: int) -> Tuple[bool, str]:
        """
        Sets manual fan speed (0-100%).
        """
        if not self.is_available or index >= self._device_count:
            return False, "NVMLが利用できません"

        handle = ctypes.c_void_p()
        if self._nvml.nvmlDeviceGetHandleByIndex_v2(ctypes.c_uint(index), ctypes.byref(handle)) != NVML_SUCCESS:
            return False, "デバイスハンドル取得失敗"

        # Try nvmlDeviceSetFanSpeed_v2 (fan 0)
        try:
            ret = self._nvml.nvmlDeviceSetFanSpeed_v2(handle, ctypes.c_uint(0), ctypes.c_uint(percent))
        except Exception:
            return False, "ファン制御機能が未サポートまたは権限不足です"

        if ret == NVML_SUCCESS:
            return True, f"ファン速度を {percent}% に設定しました"
        elif ret == NVML_ERROR_NO_PERMISSION:
            return False, "管理者権限が必要です"
        else:
            return False, f"ファン設定失敗 (エラーコード: {ret})"

    def shutdown(self):
        if self._initialized and self._nvml:
            try:
                self._nvml.nvmlShutdown()
            except Exception:
                pass
            self._initialized = False
