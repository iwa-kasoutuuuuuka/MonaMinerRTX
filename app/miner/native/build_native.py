"""
Builds app/miner/native/lyra2re2_cpu.dll (CPU Lyra2REv2 scanner) with MinGW-w64 gcc.

    python app/miner/native/build_native.py

A prebuilt DLL is committed, so this is only needed after changing src/. The DLL is linked
statically (no MinGW runtime DLLs needed) and must use -fno-strict-aliasing.
"""
import glob
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "src")
OUT = os.path.join(HERE, "lyra2re2_cpu.dll")


def find_gcc() -> str:
    gcc = shutil.which("gcc")
    if gcc:
        return gcc
    for cand in (r"C:\msys64\ucrt64\bin\gcc.exe", r"C:\msys64\mingw64\bin\gcc.exe"):
        if os.path.exists(cand):
            return cand
    sys.exit("gcc (MinGW-w64) not found")


def main():
    sources = [os.path.join(SRC, "cpu_miner.c"), os.path.join(SRC, "Lyra2.c"), os.path.join(SRC, "Sponge.c")]
    sources += sorted(glob.glob(os.path.join(SRC, "sha3", "*.c")))
    cmd = [find_gcc(), "-O3", "-fno-strict-aliasing", "-shared", "-static", "-o", OUT,
           *sources, "-I" + SRC, "-I" + os.path.join(SRC, "sha3")]
    subprocess.check_call(cmd)
    print("built", OUT, os.path.getsize(OUT), "bytes")


if __name__ == "__main__":
    main()
