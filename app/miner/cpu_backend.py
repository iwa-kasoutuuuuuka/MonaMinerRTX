"""
ctypes binding of the native CPU Lyra2REv2 scanner (app/miner/native/lyra2re2_cpu.dll).

Each call scans a nonce range on the calling thread and releases the GIL, so several Python
threads scan in parallel on several cores.
"""
import ctypes
import os
import sys

MAX_FOUND = 16
DLL_NAME = "lyra2re2_cpu.dll"


class CpuBackendUnavailable(RuntimeError):
    pass


def _dll_candidates():
    here = os.path.join(os.path.dirname(os.path.abspath(__file__)), "native", DLL_NAME)
    yield here
    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
        yield os.path.join(base, "app", "miner", "native", DLL_NAME)
        yield os.path.join(getattr(sys, "_MEIPASS", base), "app", "miner", "native", DLL_NAME)


class CpuBackend:
    _lib = None

    @classmethod
    def load(cls):
        if cls._lib is not None:
            return cls._lib
        last_error = None
        for path in _dll_candidates():
            if not os.path.exists(path):
                continue
            try:
                lib = ctypes.CDLL(path)
                lib.cpu_scan.argtypes = [ctypes.c_char_p, ctypes.c_uint32, ctypes.c_uint32,
                                         ctypes.c_uint32, ctypes.c_uint32,
                                         ctypes.POINTER(ctypes.c_uint32), ctypes.c_uint32]
                lib.cpu_scan.restype = ctypes.c_uint32
                lib.cpu_hash.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
                lib.cpu_hash.restype = None
                cls._lib = lib
                return lib
            except OSError as e:
                last_error = e
        raise CpuBackendUnavailable(f"{DLL_NAME} を読み込めません: {last_error or '見つかりません'}")

    @classmethod
    def is_available(cls) -> bool:
        try:
            cls.load()
            return True
        except CpuBackendUnavailable:
            return False

    @classmethod
    def hash80(cls, header80: bytes) -> bytes:
        out = ctypes.create_string_buffer(32)
        cls.load().cpu_hash(header80, out)
        return out.raw

    @classmethod
    def scan(cls, header76: bytes, start: int, count: int, target_hi: int, target_lo: int):
        """Returns (number of winners, first winners)."""
        found = (ctypes.c_uint32 * MAX_FOUND)()
        n = cls.load().cpu_scan(header76, start & 0xFFFFFFFF, count, target_hi, target_lo, found, MAX_FOUND)
        return n, [int(found[i]) for i in range(min(n, MAX_FOUND))]
