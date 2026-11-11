@echo off
chcp 65001 >nul
rem 在虚拟环境里运行入口脚本，不弹控制台窗口。
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\pythonw.exe" (
    echo [PDF Image Editor] 还没有安装运行环境。
    echo [PDF Image Editor] 请先双击 setup.bat，或在命令行执行：uv sync
    pause
    exit /b 1
)

start "" ".venv\Scripts\pythonw.exe" "main.pyw"
