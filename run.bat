@echo off
cd /d "%~dp0"

if not exist venv\Scripts\pythonw.exe (
    echo Virtual environment not found. Running install first...
    call install.bat
)

:: Kill any existing instance
taskkill /F /IM pythonw.exe /FI "WINDOWTITLE eq USCIS Monitor" >nul 2>&1
timeout /t 2 /nobreak >nul

:: Launch in background (no console window)
start "USCIS Monitor" venv\Scripts\pythonw.exe main.py
