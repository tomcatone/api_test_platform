@echo off
setlocal enabledelayedexpansion
title API Test Platform v4
cd /d "%~dp0"

echo.
echo  ==========================================
echo   API Interface Test Platform v4
echo  ==========================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found.
    echo Please install: https://www.python.org/downloads/
    echo Check "Add Python to PATH" during install.
    pause
    exit /b 1
)

if not exist "venv\Scripts\python.exe" (
    echo [SETUP] First run - setting up environment...
    echo.
    echo [1/3] Creating virtual environment...
    python -m venv venv
    if errorlevel 1 (
        echo [ERROR] Failed to create venv.
        pause & exit /b 1
    )
    echo [2/3] Installing packages...
    venv\Scripts\pip install -r requirements.txt -q
    if errorlevel 1 (
        echo Retrying with mirror...
        venv\Scripts\pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple -q
        if errorlevel 1 (
            echo [ERROR] pip install failed. Check network.
            pause & exit /b 1
        )
    )
    echo [3/3] Initializing database...
    venv\Scripts\python manage.py makemigrations --verbosity 0
    venv\Scripts\python manage.py migrate --verbosity 0
    if errorlevel 1 (
        echo [ERROR] Database init failed.
        pause & exit /b 1
    )
    echo.
    echo [DONE] Setup complete!
    echo.
)

echo Checking dependencies...
venv\Scripts\pip install -r requirements.txt -q 2>nul
if errorlevel 1 (
    venv\Scripts\pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple -q 2>nul
)

echo Applying database migrations...
venv\Scripts\python manage.py migrate --verbosity 0 2>nul

set PORT=8000
netstat -an 2>nul | findstr /C:":8000 " | findstr /C:"LISTENING" >nul 2>&1
if not errorlevel 1 (
    echo Port 8000 is in use, switching to 8080...
    set PORT=8080
)

echo.
echo  ------------------------------------------
echo   URL : http://127.0.0.1:!PORT!
echo   Stop: Ctrl+C
echo  ------------------------------------------
echo.

start /b cmd /c "timeout /t 2 >nul && start http://127.0.0.1:!PORT!"
venv\Scripts\python manage.py runserver 0.0.0.0:!PORT!
pause
