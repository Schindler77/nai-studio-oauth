@echo off
setlocal
cd /d "%~dp0"
rem First run: create a private Python environment and install PySide6 (~200 MB).
if not exist ".venv\installed.ok" (
  echo [1/2] Creating Python environment in .venv ...
  py -3 -m venv .venv 2>nul || python -m venv .venv
  if not exist ".venv\Scripts\python.exe" (
    echo.
    echo Python 3.10 or newer is required: https://www.python.org/downloads/
    echo During install, check "Add python.exe to PATH".
    pause
    exit /b 1
  )
  echo [2/2] Installing PySide6 ...
  ".venv\Scripts\python.exe" -m pip install --upgrade pip
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
  if errorlevel 1 (
    echo Install failed. Check your internet connection and run again.
    pause
    exit /b 1
  )
  echo ok> ".venv\installed.ok"
)
start "" ".venv\Scripts\pythonw.exe" main.py %*
