@echo off
chcp 65001 > nul
cd /d "%~dp0"
bin\monacoin-cli.exe -conf="%~dp0monacoin.conf" -rpcport=9402 %*
