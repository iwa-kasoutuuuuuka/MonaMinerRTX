@echo off
chcp 65001 > nul
echo ===================================================
echo   MonaMiner RTX - モナコイン GUI マイナー
echo   RTX 5080 (Blackwell) 特化型 マイニングスタジオ
echo ===================================================
echo.

python main.py
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [エラー] アプリケーションの実行中に問題が発生しました。
    pause
)
