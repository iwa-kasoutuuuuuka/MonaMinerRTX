@echo off
chcp 65001 > nul
title MonaMinerRTX - 即時テスト用 Regtest ソロマイニング環境
cd /d "%~dp0"

echo ==================================================================
echo   MonaMinerRTX - 即時テスト用 Regtest ソロマイニング環境
echo ==================================================================
echo.
echo Monacoin Core の Regtest クラスタを起動しています...
echo.

python run_regtest_env.py
if %errorlevel% neq 0 (
    echo.
    echo [エラー] Python環境の実行に失敗しました。
    pause
)
