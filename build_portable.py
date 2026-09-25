import os
import sys
import shutil
import zipfile
import subprocess

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
DIST_DIR = os.path.join(PROJECT_DIR, "dist")
OUTPUT_FOLDER = os.path.join(DIST_DIR, "MonaMinerRTX")
ZIP_NAME = "MonaMinerRTX_Portable_v1.0.0.zip"
ZIP_PATH = os.path.join(DIST_DIR, ZIP_NAME)

def build():
    print("=" * 60)
    print("  MonaMiner RTX 配布用ポータブル版ビルドスクリプト")
    print("=" * 60)

    # 1. Clean previous build
    if os.path.exists(DIST_DIR):
        print("\n[1/5] 既存の dist ディレクトリをクリーンアップ中...")
        try:
            shutil.rmtree(DIST_DIR)
        except Exception as e:
            print(f"  警告: 一部ファイルを削除できませんでした: {e}")

    # 2. Run PyInstaller
    print("\n[2/5] PyInstaller によるコンパイル実行中 (PySide6 + NVML 同梱)...")
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
        "--distpath", DIST_DIR,
        "--workpath", os.path.join(PROJECT_DIR, "build"),
        os.path.join(PROJECT_DIR, "main.py")
    ]

    print("  実行コマンド:", " ".join(cmd))
    res = subprocess.run(cmd, cwd=PROJECT_DIR)
    if res.returncode != 0:
        print(f"\n[エラー] PyInstaller のビルドに失敗しました (Code: {res.returncode})")
        sys.exit(res.returncode)

    # 3. Copy documentation and helpers
    print("\n[3/5] 配布用ドキュメントおよび起動バッチを同梱中...")
    files_to_copy = ["README.md", "GEMINI.md", "diagnose.py", "run.bat"]
    for fname in files_to_copy:
        src = os.path.join(PROJECT_DIR, fname)
        if os.path.exists(src):
            shutil.copy2(src, OUTPUT_FOLDER)
            print(f"  - コピー: {fname}")

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
