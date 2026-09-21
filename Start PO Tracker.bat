@echo off
REM Double-click this file to start PO Tracker (Windows).
REM First run installs everything needed (takes a minute or two and needs
REM internet access); every run after that starts in a few seconds.
cd /d "%~dp0"

REM Windows ships a fake "python.exe" that just prints an install prompt and
REM exits - "where python" finds it even when real Python isn't installed, so
REM we actually try to run it instead of just checking it exists.
python -c "print('PYTHON_OK')" 2>nul | findstr /C:"PYTHON_OK" >nul
if errorlevel 1 (
    echo ============================================================
    echo   Python was not found ^(or only the Windows Store shortcut is^)
    echo ============================================================
    echo.
    echo Step 1: Turn off the fake shortcut, if it's there -
    echo   Settings -^> Apps -^> Advanced app settings -^> App execution aliases
    echo   Turn OFF the toggles for "python.exe" and "python3.exe"
    echo.
    echo Step 2: Install real Python -
    echo   Go to https://www.python.org/downloads/ and click Download Python
    echo   IMPORTANT: on the first install screen, check the box that says
    echo   "Add python.exe to PATH" before clicking Install Now
    echo.
    echo Step 3: Double-click this file again.
    echo.
    pause
    exit /b 1
)

REM Checking for ".venv\.install_complete" (not just ".venv" existing) means
REM a previous attempt that got interrupted partway - e.g. by the Python
REM detection problems above - doesn't get mistaken for a finished install
REM and silently skipped forever.
if not exist ".venv\.install_complete" (
    echo First-time setup - this takes a minute...
    python -m venv .venv
    if not exist ".venv\Scripts\python.exe" (
        echo.
        echo Something went wrong creating the Python environment.
        echo Try closing this window and double-clicking this file again.
        echo If it keeps failing, reinstall Python from https://www.python.org/downloads/
        echo and make sure "Add python.exe to PATH" was checked during install.
        pause
        exit /b 1
    )
    REM Calling pip.exe directly to upgrade itself can fail on Windows with
    REM "To modify pip, please run: python.exe -m pip install --upgrade pip"
    REM - it can't safely overwrite its own running executable file. Running
    REM it as "python -m pip" instead avoids that entirely, and we don't stop
    REM the setup if this optional upgrade step fails either way.
    .venv\Scripts\python.exe -m pip install --upgrade pip -q
    .venv\Scripts\python.exe -m pip install -r requirements.txt -q
    if errorlevel 1 (
        echo.
        echo Installing the required packages failed - check the messages above.
        echo Make sure you're connected to the internet, then try again.
        pause
        exit /b 1
    )
    echo done > ".venv\.install_complete"
)

.venv\Scripts\python run_local.py

echo.
pause
