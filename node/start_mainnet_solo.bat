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
if not exist "%~dp0monacoin.conf" (
    copy /y "%~dp0monacoin.conf.template" "%~dp0monacoin.conf" > nul
    echo ※ monacoin.conf を初期状態で作成しました。RPC パスワードは MonaMinerRTX の次回起動時に
    echo   （ノード停止中に）自動でランダムな値へ置き換えられます。
    echo.
)
echo ノードを起動しています...
if not exist "%~dp0mainnet_data" mkdir "%~dp0mainnet_data"
bin\monacoind.exe -conf="%~dp0monacoin.conf" -datadir="%~dp0mainnet_data"

if %errorlevel% neq 0 (
    echo.
    echo [エラー] monacoind.exe の起動に失敗しました。
    echo   ※ 上に「Cannot obtain a lock on data directory」と出ている場合は、すでに別のノードが
    echo     この mainnet_data で動いています。このウィンドウは閉じて構いません。
    pause
)
