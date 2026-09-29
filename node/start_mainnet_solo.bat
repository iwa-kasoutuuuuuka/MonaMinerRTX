@echo off
chcp 65001 > nul
title MonaMinerRTX - Monacoin Core 本番メインネット ノード起動
cd /d "%~dp0"

echo ==================================================================
echo   MonaMinerRTX - Monacoin Core メインネット (Mainnet) ノード
echo ==================================================================
echo.
echo 設定ファイル: monacoin.conf
echo RPC ポート: 9402
echo RPC ユーザー: monacoinrpc
echo.
echo ※ ブロックチェーンの初期同期（約10GB〜）にはネットワーク回線と時間がかかります。
echo ※ 同期完了後、MonaMinerRTX で完全な独立ソロマイニングが可能になります。
echo.
echo ノードを起動しています...
if not exist "%~dp0mainnet_data" mkdir "%~dp0mainnet_data"
bin\monacoind.exe -conf="%~dp0monacoin.conf" -datadir="%~dp0mainnet_data"

if %errorlevel% neq 0 (
    echo.
    echo [エラー] monacoind.exe の起動に失敗しました。
    pause
)
