@echo off
chcp 65001 >nul
echo 启动 API 测试平台 v2...
call venv\Scripts\activate.bat
echo 访问: http://127.0.0.1:8000  (Ctrl+C 停止)
python manage.py runserver 0.0.0.0:8000
pause
