#!/bin/bash
# API測試平臺 一鍵安裝腳本
# Python 3.13+ 虛擬環境

echo "======================================"
echo "  API 接口測試平臺 - 環境安裝腳本"
echo "======================================"

# 創建虛擬環境
echo "[1/5] 創建 Python 虛擬環境..."
python3 -m venv venv
source venv/bin/activate

# 升級 pip
echo "[2/5] 升級 pip..."
pip install --upgrade pip -q

# 安裝依賴
echo "[3/5] 安裝依賴包..."
pip install -r requirements.txt -q

# 初始化數據庫
echo "[4/5] 初始化數據庫..."
python manage.py makemigrations
python manage.py migrate

# 創建超級用戶 (可選)
echo "[5/5] 完成！"
echo ""
echo "======================================"
echo "  啟動命令："
echo "  source venv/bin/activate"
echo "  python manage.py runserver 0.0.0.0:8000"
echo "  訪問: http://127.0.0.1:8000"
echo "======================================"
