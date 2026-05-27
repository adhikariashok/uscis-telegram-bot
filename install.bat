@echo off
title USCIS Monitor — Install
echo ========================================
echo  USCIS Monitor Setup
echo ========================================
echo.

:: Use Python 3.13 (stable) — avoids greenlet build issues with 3.14
py -3.13 --version >nul 2>&1
if errorlevel 1 (
    echo Trying default Python...
    python --version >nul 2>&1
    if errorlevel 1 (
        echo ERROR: Python not found. Install Python 3.12 or 3.13 from https://python.org
        pause
        exit /b 1
    )
    set PYTHON=python
) else (
    set PYTHON=py -3.13
)

echo Using: %PYTHON%
echo.

echo [1/3] Creating virtual environment with Python 3.13...
if exist venv rmdir /s /q venv
%PYTHON% -m venv venv
if errorlevel 1 ( echo Failed to create venv. & pause & exit /b 1 )

echo [2/3] Installing Python dependencies...
venv\Scripts\pip install --upgrade pip -q
venv\Scripts\pip install -r requirements.txt
if errorlevel 1 ( echo Dependency install failed. & pause & exit /b 1 )

echo [3/3] Creating desktop shortcut...
powershell -Command ^
  "$ws = New-Object -ComObject WScript.Shell; ^
   $s = $ws.CreateShortcut('%USERPROFILE%\Desktop\USCIS Monitor.lnk'); ^
   $s.TargetPath = '%~dp0run.bat'; ^
   $s.WorkingDirectory = '%~dp0'; ^
   $s.Description = 'USCIS Case Monitor'; ^
   $s.Save()"

echo.
echo ========================================
echo  Installation complete!
echo  Chrome is used automatically for login
echo  (no separate browser download needed).
echo.
echo  Run "run.bat" or the desktop shortcut
echo  to start the app.
echo ========================================
pause
