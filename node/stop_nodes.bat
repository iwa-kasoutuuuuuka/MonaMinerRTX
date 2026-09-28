@echo off
chcp 65001 > nul
cd /d "%~dp0"
echo 停止中...
bin\monacoin-cli.exe -rpcuser=monacoinrpc -rpcpassword=rpcpassword -rpcport=9402 stop 2>nul
bin\monacoin-cli.exe -rpcuser=monacoinrpc -rpcpassword=rpcpassword -rpcport=9403 stop 2>nul
echo ノード停止コマンドを発行しました。
timeout /t 2 > nul
