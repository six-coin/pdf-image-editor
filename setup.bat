@echo off
setlocal
cd /d "%~dp0"

where uv >nul 2>nul
if errorlevel 1 (
    echo Failed: Install uv first: https://docs.astral.sh/uv/
    pause
    exit /b 1
)

uv sync
if errorlevel 1 (
    echo Failed: Dependency installation failed. Please check your network and try again.
    pause
    exit /b 1
)

echo Done.
pause
