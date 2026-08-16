@echo off
chcp 65001 >nul
echo 启动矢量图形编辑器...
echo.

cd /d "%~dp0src"
python main.py

if errorlevel 1 (
    echo.
    echo 程序运行出错！请检查错误信息。
    pause
)

pause