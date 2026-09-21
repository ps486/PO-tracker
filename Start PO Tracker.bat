@echo off
REM Double-click this file to start PO Tracker (Windows).
REM First run installs everything needed (takes a minute or two and needs
REM internet access); every run after that starts in a few seconds.
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo Python is not installed on this computer.
    echo Install it from https://www.python.org/downloads/ - during install, check the box
    echo that says "Add Python to PATH" - then double-click this file again.
    pause
    exit /b 1
)

if not exist ".venv" (
    echo First-time setup - this takes a minute...
    python -m venv .venv
    .venv\Scripts\pip install --upgrade pip -q
    .venv\Scripts\pip install -r requirements.txt -q
)

.venv\Scripts\python run_local.py

echo.
pause
