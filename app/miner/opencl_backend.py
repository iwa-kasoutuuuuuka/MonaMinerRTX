"""
OpenCL ctypes low-level backend for MonaMiner.
Enables native GPU mining on AMD Radeon, NVIDIA GeForce, and Intel GPUs
directly using Windows System32/OpenCL.dll without external binaries or heavy dependencies.
"""

import ctypes
from ctypes import (
    c_int, c_uint, c_ulonglong, c_size_t, c_char_p, c_void_p,
    POINTER, byref, create_string_buffer, sizeof
)
import sys

# OpenCL Constants
CL_SUCCESS = 0
CL_DEVICE_TYPE_DEFAULT = (1 << 0)
CL_DEVICE_TYPE_CPU = (1 << 1)
CL_DEVICE_TYPE_GPU = (1 << 2)
CL_DEVICE_TYPE_ACCELERATOR = (1 << 3)
CL_DEVICE_TYPE_CUSTOM = (1 << 4)
CL_DEVICE_TYPE_ALL = 0xFFFFFFFF

# cl_platform_info
CL_PLATFORM_PROFILE = 0x0900
CL_PLATFORM_VERSION = 0x0901
CL_PLATFORM_NAME = 0x0902
CL_PLATFORM_VENDOR = 0x0903
CL_PLATFORM_EXTENSIONS = 0x0904

# cl_device_info
CL_DEVICE_NAME = 0x102B
CL_DEVICE_VENDOR = 0x102C
CL_DRIVER_VERSION = 0x102D
CL_DEVICE_PROFILE = 0x102E
CL_DEVICE_VERSION = 0x102F
CL_DEVICE_OPENCL_C_VERSION = 0x103D
CL_DEVICE_MAX_COMPUTE_UNITS = 0x1002
CL_DEVICE_MAX_WORK_ITEM_DIMENSIONS = 0x1003
CL_DEVICE_MAX_WORK_GROUP_SIZE = 0x1004
CL_DEVICE_MAX_CLOCK_FREQUENCY = 0x100C
CL_DEVICE_GLOBAL_MEM_SIZE = 0x101F
CL_DEVICE_MAX_MEM_ALLOC_SIZE = 0x1010

# cl_mem_flags
CL_MEM_READ_WRITE = (1 << 0)
CL_MEM_WRITE_ONLY = (1 << 1)
CL_MEM_READ_ONLY = (1 << 2)
CL_MEM_USE_HOST_PTR = (1 << 3)
CL_MEM_ALLOC_HOST_PTR = (1 << 4)
CL_MEM_COPY_HOST_PTR = (1 << 5)

# cl_program_build_info
CL_PROGRAM_BUILD_STATUS = 0x1181
CL_PROGRAM_BUILD_OPTIONS = 0x1182
CL_PROGRAM_BUILD_LOG = 0x1183

# cl_bool
CL_TRUE = 1
CL_FALSE = 0

class OpenCLException(Exception):
    def __init__(self, code, msg=""):
        super().__init__(f"OpenCL Error (Code: {code}) {msg}")
        self.code = code

class OpenCLBackend:
    _lib = None

    @classmethod
    def load_library(cls):
        if cls._lib is not None:
            return cls._lib

        dll_names = ["OpenCL.dll", "OpenCL"]
        for name in dll_names:
            try:
                cls._lib = ctypes.cdll.LoadLibrary(name)
                break
            except Exception:
                continue

        if cls._lib is None:
            raise RuntimeError("Windows System32/OpenCL.dll のロードに失敗しました。グラフィックドライバが正常にインストールされているか確認してください。")

        # Setup function signatures
        lib = cls._lib

        # clGetPlatformIDs
        lib.clGetPlatformIDs.argtypes = [c_uint, POINTER(c_void_p), POINTER(c_uint)]
        lib.clGetPlatformIDs.restype = c_int

        # clGetPlatformInfo
        lib.clGetPlatformInfo.argtypes = [c_void_p, c_uint, c_size_t, c_void_p, POINTER(c_size_t)]
        lib.clGetPlatformInfo.restype = c_int

        # clGetDeviceIDs
        lib.clGetDeviceIDs.argtypes = [c_void_p, c_ulonglong, c_uint, POINTER(c_void_p), POINTER(c_uint)]
        lib.clGetDeviceIDs.restype = c_int

        # clGetDeviceInfo
        lib.clGetDeviceInfo.argtypes = [c_void_p, c_uint, c_size_t, c_void_p, POINTER(c_size_t)]
        lib.clGetDeviceInfo.restype = c_int

        # clCreateContext
        lib.clCreateContext.argtypes = [POINTER(c_size_t), c_uint, POINTER(c_void_p), c_void_p, c_void_p, POINTER(c_int)]
        lib.clCreateContext.restype = c_void_p

        # clReleaseContext
        lib.clReleaseContext.argtypes = [c_void_p]
        lib.clReleaseContext.restype = c_int

        # clCreateCommandQueue
        lib.clCreateCommandQueue.argtypes = [c_void_p, c_void_p, c_ulonglong, POINTER(c_int)]
        lib.clCreateCommandQueue.restype = c_void_p

        # clReleaseCommandQueue
        lib.clReleaseCommandQueue.argtypes = [c_void_p]
        lib.clReleaseCommandQueue.restype = c_int

        # clCreateProgramWithSource
        lib.clCreateProgramWithSource.argtypes = [c_void_p, c_uint, POINTER(c_char_p), POINTER(c_size_t), POINTER(c_int)]
        lib.clCreateProgramWithSource.restype = c_void_p

        # clBuildProgram
        lib.clBuildProgram.argtypes = [c_void_p, c_uint, POINTER(c_void_p), c_char_p, c_void_p, c_void_p]
        lib.clBuildProgram.restype = c_int

        # clGetProgramBuildInfo
        lib.clGetProgramBuildInfo.argtypes = [c_void_p, c_void_p, c_uint, c_size_t, c_void_p, POINTER(c_size_t)]
        lib.clGetProgramBuildInfo.restype = c_int

        # clReleaseProgram
        lib.clReleaseProgram.argtypes = [c_void_p]
        lib.clReleaseProgram.restype = c_int

        # clCreateKernel
        lib.clCreateKernel.argtypes = [c_void_p, c_char_p, POINTER(c_int)]
        lib.clCreateKernel.restype = c_void_p

        # clSetKernelArg
        lib.clSetKernelArg.argtypes = [c_void_p, c_uint, c_size_t, c_void_p]
        lib.clSetKernelArg.restype = c_int

        # clReleaseKernel
        lib.clReleaseKernel.argtypes = [c_void_p]
        lib.clReleaseKernel.restype = c_int

        # clCreateBuffer
        lib.clCreateBuffer.argtypes = [c_void_p, c_ulonglong, c_size_t, c_void_p, POINTER(c_int)]
        lib.clCreateBuffer.restype = c_void_p

        # clEnqueueWriteBuffer
        lib.clEnqueueWriteBuffer.argtypes = [c_void_p, c_void_p, c_uint, c_size_t, c_size_t, c_void_p, c_uint, c_void_p, c_void_p]
        lib.clEnqueueWriteBuffer.restype = c_int

        # clEnqueueReadBuffer
        lib.clEnqueueReadBuffer.argtypes = [c_void_p, c_void_p, c_uint, c_size_t, c_size_t, c_void_p, c_uint, c_void_p, c_void_p]
        lib.clEnqueueReadBuffer.restype = c_int

        # clEnqueueNDRangeKernel
        lib.clEnqueueNDRangeKernel.argtypes = [c_void_p, c_void_p, c_uint, POINTER(c_size_t), POINTER(c_size_t), POINTER(c_size_t), c_uint, c_void_p, c_void_p]
        lib.clEnqueueNDRangeKernel.restype = c_int

        # clFinish
        lib.clFinish.argtypes = [c_void_p]
        lib.clFinish.restype = c_int

        # clReleaseMemObject
        lib.clReleaseMemObject.argtypes = [c_void_p]
        lib.clReleaseMemObject.restype = c_int

        return lib

    @classmethod
    def get_platforms(cls):
        lib = cls.load_library()
        num = c_uint(0)
        err = lib.clGetPlatformIDs(0, None, byref(num))
        if err != CL_SUCCESS or num.value == 0:
            return []

        platforms = (c_void_p * num.value)()
        lib.clGetPlatformIDs(num.value, platforms, None)

        res = []
        for p in platforms:
            name_buf = create_string_buffer(512)
            vendor_buf = create_string_buffer(512)
            lib.clGetPlatformInfo(p, CL_PLATFORM_NAME, 512, name_buf, None)
            lib.clGetPlatformInfo(p, CL_PLATFORM_VENDOR, 512, vendor_buf, None)
            res.append({
                "id": p,
                "name": name_buf.value.decode("utf-8", errors="ignore").strip(),
                "vendor": vendor_buf.value.decode("utf-8", errors="ignore").strip(),
            })
        return res

    @classmethod
    def get_devices(cls, platform_id, device_type=CL_DEVICE_TYPE_GPU):
        lib = cls.load_library()
        num = c_uint(0)
        err = lib.clGetDeviceIDs(platform_id, device_type, 0, None, byref(num))
        if err != CL_SUCCESS or num.value == 0:
            # Fallback to all devices if GPU specific query returned 0
            if device_type != CL_DEVICE_TYPE_ALL:
                return cls.get_devices(platform_id, CL_DEVICE_TYPE_ALL)
            return []

        devices = (c_void_p * num.value)()
        lib.clGetDeviceIDs(platform_id, device_type, num.value, devices, None)

        res = []
        for d in devices:
            buf = create_string_buffer(512)
            lib.clGetDeviceInfo(d, CL_DEVICE_NAME, 512, buf, None)
            dev_name = buf.value.decode("utf-8", errors="ignore").strip()

            lib.clGetDeviceInfo(d, CL_DEVICE_VENDOR, 512, buf, None)
            dev_vendor = buf.value.decode("utf-8", errors="ignore").strip()

            lib.clGetDeviceInfo(d, CL_DRIVER_VERSION, 512, buf, None)
            driver_ver = buf.value.decode("utf-8", errors="ignore").strip()

            cu = c_uint(0)
            lib.clGetDeviceInfo(d, CL_DEVICE_MAX_COMPUTE_UNITS, sizeof(cu), byref(cu), None)

            max_wg = c_size_t(0)
            lib.clGetDeviceInfo(d, CL_DEVICE_MAX_WORK_GROUP_SIZE, sizeof(max_wg), byref(max_wg), None)

            mem_bytes = c_ulonglong(0)
            lib.clGetDeviceInfo(d, CL_DEVICE_GLOBAL_MEM_SIZE, sizeof(mem_bytes), byref(mem_bytes), None)

            res.append({
                "id": d,
                "name": dev_name,
                "vendor": dev_vendor,
                "driver": driver_ver,
                "compute_units": cu.value,
                "max_work_group_size": max_wg.value,
                "global_mem_gb": round(mem_bytes.value / (1024 ** 3), 2),
            })
        return res

class OpenCLContext:
    """
    Manages an OpenCL Context, Command Queue, and Program compilation for a single device.
    """
    def __init__(self, platform_id, device_id):
        self.lib = OpenCLBackend.load_library()
        self.platform_id = platform_id
        self.device_id = device_id
        self.context = None
        self.queue = None
        self.program = None
        self.kernels = {}
        self._init_context()

    def _init_context(self):
        err = c_int(0)
        dev_arr = (c_void_p * 1)(self.device_id)

        # Context properties: [CL_CONTEXT_PLATFORM, platform_id, 0]
        # In OpenCL 1.2: CL_CONTEXT_PLATFORM = 0x1084
        CL_CONTEXT_PLATFORM = 0x1084
        props = (c_size_t * 3)(CL_CONTEXT_PLATFORM, self.platform_id, 0)

        self.context = self.lib.clCreateContext(props, 1, dev_arr, None, None, byref(err))
        if err.value != CL_SUCCESS or not self.context:
            raise OpenCLException(err.value, "clCreateContext failed")

        self.queue = self.lib.clCreateCommandQueue(self.context, self.device_id, 0, byref(err))
        if err.value != CL_SUCCESS or not self.queue:
            raise OpenCLException(err.value, "clCreateCommandQueue failed")

    def build_program(self, source_code: str, options: str = ""):
        err = c_int(0)
        c_src = source_code.encode("utf-8")
        src_buf = c_char_p(c_src)
        src_len = c_size_t(len(c_src))

        self.program = self.lib.clCreateProgramWithSource(
            self.context, 1, byref(src_buf), byref(src_len), byref(err)
        )
        if err.value != CL_SUCCESS or not self.program:
            raise OpenCLException(err.value, "clCreateProgramWithSource failed")

        dev_arr = (c_void_p * 1)(self.device_id)
        c_opt = options.encode("utf-8") if options else None

        build_err = self.lib.clBuildProgram(self.program, 1, dev_arr, c_opt, None, None)
        if build_err != CL_SUCCESS:
            # Retrieve build log
            log_size = c_size_t(0)
            self.lib.clGetProgramBuildInfo(self.program, self.device_id, CL_PROGRAM_BUILD_LOG, 0, None, byref(log_size))
            log_buf = create_string_buffer(log_size.value + 1)
            self.lib.clGetProgramBuildInfo(self.program, self.device_id, CL_PROGRAM_BUILD_LOG, log_size.value, log_buf, None)
            build_log = log_buf.value.decode("utf-8", errors="ignore")
            raise OpenCLException(build_err, f"clBuildProgram failed:\n{build_log}")

        return self.program

    def get_kernel(self, kernel_name: str):
        if kernel_name in self.kernels:
            return self.kernels[kernel_name]

        err = c_int(0)
        c_name = kernel_name.encode("utf-8")
        kernel = self.lib.clCreateKernel(self.program, c_name, byref(err))
        if err.value != CL_SUCCESS or not kernel:
            raise OpenCLException(err.value, f"clCreateKernel '{kernel_name}' failed")

        self.kernels[kernel_name] = kernel
        return kernel

    def create_buffer(self, size_bytes: int, flags: int = CL_MEM_READ_WRITE):
        err = c_int(0)
        buf = self.lib.clCreateBuffer(self.context, flags, size_bytes, None, byref(err))
        if err.value != CL_SUCCESS or not buf:
            raise OpenCLException(err.value, f"clCreateBuffer failed ({size_bytes} bytes)")
        return buf

    def set_arg_mem(self, kernel, arg_index: int, cl_buf):
        buf_ptr = c_void_p(cl_buf)
        err = self.lib.clSetKernelArg(kernel, arg_index, sizeof(c_void_p), byref(buf_ptr))
        if err != CL_SUCCESS:
            raise OpenCLException(err, f"clSetKernelArg({arg_index}) mem failed")

    def set_arg_uint(self, kernel, arg_index: int, val: int):
        c_val = c_uint(val)
        err = self.lib.clSetKernelArg(kernel, arg_index, sizeof(c_uint), byref(c_val))
        if err != CL_SUCCESS:
            raise OpenCLException(err, f"clSetKernelArg({arg_index}) uint failed")

    def set_arg_raw(self, kernel, arg_index: int, c_obj):
        err = self.lib.clSetKernelArg(kernel, arg_index, sizeof(c_obj), byref(c_obj))
        if err != CL_SUCCESS:
            raise OpenCLException(err, f"clSetKernelArg({arg_index}) raw failed")

    def write_buffer(self, cl_buf, host_ptr, size_bytes: int, blocking: bool = True):
        err = self.lib.clEnqueueWriteBuffer(
            self.queue, cl_buf, 1 if blocking else 0, 0, size_bytes, host_ptr, 0, None, None
        )
        if err != CL_SUCCESS:
            raise OpenCLException(err, "clEnqueueWriteBuffer failed")

    def read_buffer(self, cl_buf, host_ptr, size_bytes: int, blocking: bool = True):
        err = self.lib.clEnqueueReadBuffer(
            self.queue, cl_buf, 1 if blocking else 0, 0, size_bytes, host_ptr, 0, None, None
        )
        if err != CL_SUCCESS:
            raise OpenCLException(err, "clEnqueueReadBuffer failed")

    def run_kernel_1d(self, kernel, global_size: int, local_size: int = None):
        c_global = (c_size_t * 1)(global_size)
        c_local = (c_size_t * 1)(local_size) if local_size else None

        err = self.lib.clEnqueueNDRangeKernel(
            self.queue, kernel, 1, None, c_global, c_local, 0, None, None
        )
        if err != CL_SUCCESS:
            raise OpenCLException(err, "clEnqueueNDRangeKernel failed")

    def finish(self):
        self.lib.clFinish(self.queue)

    def release(self):
        for k in self.kernels.values():
            try:
                self.lib.clReleaseKernel(k)
            except Exception:
                pass
        self.kernels.clear()

        if self.program:
            try:
                self.lib.clReleaseProgram(self.program)
            except Exception:
                pass
            self.program = None

        if self.queue:
            try:
                self.lib.clReleaseCommandQueue(self.queue)
            except Exception:
                pass
            self.queue = None

        if self.context:
            try:
                self.lib.clReleaseContext(self.context)
            except Exception:
                pass
            self.context = None
