@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\pythonw.exe" (
    echo Failed: Run setup.bat first to install dependencies.
    pause
    exit /b 1
)

start "" ".venv\Scripts\pythonw.exe" "main.pyw"
