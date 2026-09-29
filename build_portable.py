import os
import sys
import shutil
import zipfile
import subprocess

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
DIST_DIR = os.path.join(PROJECT_DIR, "dist")
OUTPUT_FOLDER = os.path.join(DIST_DIR, "MonaMinerRTX")
ZIP_NAME = "MonaMinerRTX_Portable_v2.2.1.zip"
ZIP_PATH = os.path.join(DIST_DIR, ZIP_NAME)

def build():
    print("=" * 60)
    print("  MonaMiner RTX 配布用ポータブル版ビルドスクリプト v2.2.1")
    print("=" * 60)

    # 1. Clean previous build
    if os.path.exists(DIST_DIR):
        print("\n[1/5] 既存の dist ディレクトリをクリーンアップ中...")
        try:
            shutil.rmtree(DIST_DIR)
        except Exception as e:
            print(f"  警告: 一部ファイルを削除できませんでした: {e}")

    # 2. Run PyInstaller
    print("\n[2/5] PyInstaller によるコンパイル実行中 (PySide6 + NVML + 内蔵OpenCL + v2サービス 同梱)...")
    kernel_src = os.path.join(PROJECT_DIR, "app", "miner", "kernels", "lyra2v2.cl")
    cpu_dll = os.path.join(PROJECT_DIR, "app", "miner", "native", "lyra2re2_cpu.dll")
    if not os.path.exists(cpu_dll):
        print("[エラー] app/miner/native/lyra2re2_cpu.dll がありません。python app/miner/native/build_native.py を実行してください。")
        sys.exit(1)
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name=MonaMinerRTX",
        "--windowed", # No black command prompt window for the GUI
        "--onedir",   # Portable directory (Fast launch & anti-virus friendly)
        "--clean",
        "--icon=" + os.path.join(PROJECT_DIR, "assets", "icon.ico"),
        "--version-file=" + os.path.join(PROJECT_DIR, "version_info.txt"),
        "--hidden-import=pynvml",
        "--hidden-import=psutil",
        "--hidden-import=PySide6",
        "--hidden-import=PySide6.QtCore",
        "--hidden-import=PySide6.QtGui",
        "--hidden-import=PySide6.QtWidgets",
        "--hidden-import=app.miner",
        "--hidden-import=app.miner.opencl_backend",
        "--hidden-import=app.miner.opencl_miner",
        "--hidden-import=app.miner.stratum_client",
        "--hidden-import=app.miner.rpc_solo_client",
        "--hidden-import=app.miner.cpu_backend",
        "--hidden-import=app.miner.benchmark",
        "--hidden-import=app.services",
        "--hidden-import=app.services.idle_tracker",
        "--hidden-import=app.services.profit_calc",
        "--hidden-import=app.services.notifier",
        "--hidden-import=app.services.gpu_control",
        "--hidden-import=app.services.web_server",
        "--hidden-import=app.services.wallet_service",
        "--hidden-import=app.services.node_service",
        "--hidden-import=app.ui.wallet_dialog",
        f"--add-data={kernel_src};app/miner/kernels",
        f"--add-binary={cpu_dll};app/miner/native",
        "--distpath", DIST_DIR,
        "--workpath", os.path.join(PROJECT_DIR, "build"),
        os.path.join(PROJECT_DIR, "main.py")
    ]

    print("  実行コマンド:", " ".join(cmd))
    res = subprocess.run(cmd, cwd=PROJECT_DIR)
    if res.returncode != 0:
        print(f"\n[エラー] PyInstaller のビルドに失敗しました (Code: {res.returncode})")
        sys.exit(res.returncode)

    # 3. Copy documentation, helpers, and OpenCL kernels
    print("\n[3/5] 配布用ドキュメント、アセット、カーネルおよび起動バッチを同梱中...")
    files_to_copy = ["README.md", "GEMINI.md", "diagnose.py", "run.bat"]
    for fname in files_to_copy:
        src = os.path.join(PROJECT_DIR, fname)
        if os.path.exists(src):
            shutil.copy2(src, OUTPUT_FOLDER)
            print(f"  - コピー: {fname}")

    # Copy assets directory
    src_assets = os.path.join(PROJECT_DIR, "assets")
    dst_assets = os.path.join(OUTPUT_FOLDER, "assets")
    if os.path.exists(src_assets):
        if os.path.exists(dst_assets):
            shutil.rmtree(dst_assets)
        shutil.copytree(src_assets, dst_assets)
        print("  - コピー: assets/ (icon.png, icon.ico)")

    # Copy app/miner/kernels directory
    src_kernels = os.path.join(PROJECT_DIR, "app", "miner", "kernels")
    dst_kernels = os.path.join(OUTPUT_FOLDER, "app", "miner", "kernels")
    if os.path.exists(src_kernels):
        if os.path.exists(dst_kernels):
            shutil.rmtree(dst_kernels)
        shutil.copytree(src_kernels, dst_kernels)
        print("  - コピー: app/miner/kernels/ (lyra2v2.cl)")

    # Copy the native CPU miner next to the executable as well (loaded from app/miner/native)
    dst_native = os.path.join(OUTPUT_FOLDER, "app", "miner", "native")
    os.makedirs(dst_native, exist_ok=True)
    shutil.copy2(cpu_dll, dst_native)
    print("  - コピー: app/miner/native/lyra2re2_cpu.dll")

    # Copy node directory (scripts, conf, bin if present, excluding large data dirs)
    src_node = os.path.join(PROJECT_DIR, "node")
    dst_node = os.path.join(OUTPUT_FOLDER, "node")
    if os.path.exists(src_node):
        if os.path.exists(dst_node):
            shutil.rmtree(dst_node)
        os.makedirs(dst_node, exist_ok=True)
        # Copy root files of node/
        for item in os.listdir(src_node):
            s_item = os.path.join(src_node, item)
            d_item = os.path.join(dst_node, item)
            if os.path.isfile(s_item):
                shutil.copy2(s_item, d_item)
            elif os.path.isdir(s_item) and item == "bin":
                shutil.copytree(s_item, d_item)
        print("  - コピー: node/ (Monacoin Core バイナリ、設定、ソロ起動スクリプト群)")

    # Portable run.bat
    portable_bat = os.path.join(OUTPUT_FOLDER, "起動する.bat")
    with open(portable_bat, "w", encoding="utf-8") as f:
        f.write("@echo off\r\n")
        f.write("chcp 65001 > nul\r\n")
        f.write("cd /d \"%~dp0\"\r\n")
        f.write("start \"\" \"MonaMinerRTX.exe\"\r\n")
    print("  - 作成: 起動する.bat")

    # 4. Verification Test
    print("\n[4/5] 生成された実行ファイル (MonaMinerRTX.exe) のテスト検証...")
    exe_path = os.path.join(OUTPUT_FOLDER, "MonaMinerRTX.exe")
    if os.path.exists(exe_path):
        print(f"  - 実行ファイル確認: {exe_path} ({os.path.getsize(exe_path) / 1024:.1f} KB)")
        print("  -> バイナリ生成成功")
    else:
        print("  -> ERROR: MonaMinerRTX.exe が見つかりません")
        sys.exit(1)

    # 5. Create Zip Archive
    print("\n[5/5] 配布用 ZIP アーカイブを作成中...")
    with zipfile.ZipFile(ZIP_PATH, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(OUTPUT_FOLDER):
            for file in files:
                abs_file = os.path.join(root, file)
                rel_file = os.path.relpath(abs_file, DIST_DIR)
                zipf.write(abs_file, rel_file)

    zip_size_mb = os.path.getsize(ZIP_PATH) / (1024 * 1024)
    print(f"  - 配布アーカイブ: {ZIP_PATH} ({zip_size_mb:.2f} MB)")

    print("\n" + "=" * 60)
    print("  ポータブル版のビルドが正常に完了しました！[COMPLETE]")
    print(f"  配布用ZIP: {ZIP_PATH}")
    print(f"  展開フォルダ: {OUTPUT_FOLDER}")
    print("=" * 60)

if __name__ == "__main__":
    build()
