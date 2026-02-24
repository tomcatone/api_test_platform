@echo off
chcp 65001 >nul
echo ======================================
echo   API 测试平台 v2 - Windows 安装脚本
echo ======================================

python --version >nul 2>&1
if errorlevel 1 (echo [错误] 未找到 Python 3.13+，请先安装 & pause & exit /b 1)

echo [1/5] Python 版本:
python --version

echo [2/5] 创建虚拟环境...
python -m venv venv
if errorlevel 1 (echo [错误] 创建虚拟环境失败 & pause & exit /b 1)

echo [3/5] 安装依赖（含 httpx / PyMySQL）...
call venv\Scripts\activate.bat
python -m pip install --upgrade pip -q
pip install -r requirements.txt
if errorlevel 1 (
    echo [提示] 尝试使用国内镜像...
    pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
)

echo [4/5] 初始化数据库...
python manage.py makemigrations
python manage.py migrate
if errorlevel 1 (echo [错误] 数据库初始化失败 & pause & exit /b 1)

echo [5/5] 完成！
echo.
echo  启动: 双击 start.bat
echo  访问: http://127.0.0.1:8000
echo.
set /p Q=是否立即启动？(Y/N):
if /i "%Q%"=="Y" python manage.py runserver 0.0.0.0:8000
pause
