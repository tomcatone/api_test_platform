@echo off
setlocal enabledelayedexpansion
title API Test Platform v4 - Setup
cd /d "%~dp0"

echo.
echo  ==========================================
echo   API Test Platform v4 - Setup
echo  ==========================================
echo.

echo Python version check:
python --version
if errorlevel 1 (
    echo [ERROR] Python not found.
    echo Install from https://www.python.org/downloads/
    pause & exit /b 1
)

echo.
echo [1/3] Creating virtual environment...
python -m venv venv
if errorlevel 1 (echo [ERROR] Failed & pause & exit /b 1)

echo [2/3] Installing packages...
venv\Scripts\pip install -r requirements.txt
if errorlevel 1 (
    echo Retrying with Tsinghua mirror...
    venv\Scripts\pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
    if errorlevel 1 (echo [ERROR] Install failed & pause & exit /b 1)
)

echo [3/3] Initializing database...
venv\Scripts\python manage.py makemigrations
venv\Scripts\python manage.py migrate
if errorlevel 1 (echo [ERROR] Database failed & pause & exit /b 1)

echo.
echo  Setup complete! Run: start.bat
echo.
set /p Q=Start now? (Y/N): 
if /i "!Q!"=="Y" call start.bat
pause
