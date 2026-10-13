@echo off
chcp 65001 > nul
cd /d "%~dp0"
echo ===================================================
echo   MonaMiner RTX - ワンクリック・ソロ採掘
echo   ノード起動 → 同期確認 → 採掘開始 を自動で行います
echo ===================================================
echo.

python main.py --solo
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [エラー] アプリケーションの実行中に問題が発生しました。
    pause
)
