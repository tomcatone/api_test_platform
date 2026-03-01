@echo off
setlocal
cd /d "%~dp0"
title Build EXE - API Test Platform v4

echo.
echo  ==========================================
echo   Build launcher EXE - API Test Platform
echo  ==========================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found.
    pause & exit /b 1
)

echo [1/3] Installing PyInstaller...
pip install pyinstaller -q
if errorlevel 1 (
    pip install pyinstaller -i https://pypi.tuna.tsinghua.edu.cn/simple -q
)

echo [2/3] Compiling launcher.py to EXE...
pyinstaller --onefile --windowed --name=API-TestPlatform-v4 launcher.py --distpath . --workpath build_tmp --specpath build_tmp
if errorlevel 1 (
    echo [ERROR] Compile failed.
    pause & exit /b 1
)

echo [3/3] Cleaning up build files...
if exist build_tmp rmdir /s /q build_tmp

echo.
echo  ==========================================
echo   Done! EXE created: API-TestPlatform-v4.exe
echo   Double-click it to start the platform.
echo  ==========================================
echo.
pause
