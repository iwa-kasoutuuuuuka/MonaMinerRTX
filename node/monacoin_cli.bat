@echo off
chcp 65001 > nul
cd /d "%~dp0"
bin\monacoin-cli.exe -rpcuser=monacoinrpc -rpcpassword=rpcpassword -rpcport=9402 %*
