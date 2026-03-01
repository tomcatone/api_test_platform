@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
title API Test Platform v4

if not exist "venv\Scripts\python.exe" (
    echo Not installed yet. Run setup.bat first.
    pause & exit /b 1
)

venv\Scripts\python manage.py migrate --verbosity 0 2>nul

set PORT=8000
netstat -an 2>nul | findstr /C:":8000 " | findstr /C:"LISTENING" >nul 2>&1
if not errorlevel 1 (
    set PORT=8080
)

start /b cmd /c "timeout /t 2 >nul && start http://127.0.0.1:!PORT!"
echo Starting at http://127.0.0.1:!PORT!
venv\Scripts\python manage.py runserver 0.0.0.0:!PORT!
pause
