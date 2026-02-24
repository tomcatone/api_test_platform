# API 接口測試平臺

基於 **Django 5.1 + SQLite3** 的接口測試平臺，支持 Python 3.13+。

---

## 🚀 Windows 快速啟動（推薦）

### 前提條件
- 安裝 Python 3.13+（官網 https://www.python.org/downloads/）
- 安裝時 **勾選 "Add Python to PATH"**

### 步驟

**第一步：安裝（只需執行一次）**

雙擊 `setup.bat` → 自動創建虛擬環境、安裝依賴、初始化數據庫

**第二步：啟動**

雙擊 `start.bat` → 瀏覽器打開 http://127.0.0.1:8000

---

## 🖥️ 手動安裝（命令提示符）

```bat
REM 進入項目目錄
cd api_test_platform

REM 創建虛擬環境
python -m venv venv

REM 激活虛擬環境
venv\Scripts\activate

REM 安裝依賴
pip install -r requirements.txt

REM 初始化數據庫
python manage.py makemigrations
python manage.py migrate

REM 啟動服務
python manage.py runserver 0.0.0.0:8000
```

瀏覽器訪問：http://127.0.0.1:8000

---

## ⚠️ Windows 常見問題

| 問題 | 解決方法 |
|------|----------|
| `python` 不是內部命令 | Python 安裝時未勾選 "Add to PATH"，重裝並勾選 |
| `pip` 安裝超時 | 使用國內鏡像：`pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple` |
| 端口 8000 被占用 | 改用其他端口：`python manage.py runserver 0.0.0.0:8080` |
| 雙擊 .bat 閃退 | 右鍵 → 以管理員身份運行；或在 CMD 中手動執行 |
| 中文亂碼 | CMD 執行 `chcp 65001` 切換 UTF-8 |
| venv\Scripts\activate 報錯 | PowerShell 需執行：`Set-ExecutionPolicy RemoteSigned` |

---

## 📁 項目結構

```
api_test_platform\
├── setup.bat                ← Windows 一鍵安裝
├── start.bat                ← Windows 一鍵啟動
├── manage.py
├── requirements.txt
├── db.sqlite3               (運行後自動生成)
├── api_test_platform\
│   ├── settings.py
│   ├── urls.py
│   └── wsgi.py
├── apps\core\
│   ├── models.py            數據模型
│   ├── views.py             REST API 視圖
│   ├── urls.py              路由
│   └── executor.py          執行引擎
└── templates\
    └── index.html           前端單頁應用
```

---

## 🎯 功能說明

### 全局變量 / Token
- 生成 UUID / HEX32 / HEX64 / URLSafe Token 並保存為全局變量
- 在接口 URL、Headers、Body 中用 `{{變量名}}` 引用

```
URL:     https://api.example.com/{{env}}/user
Headers: {"Authorization": "Bearer {{token}}"}
Body:    {"user_id": "{{user_id}}"}
```

### 跨接口傳值
在接口「提取變量」中配置：
- **變量名**：`token`
- **提取路徑**：`data.token`（支持 `data.list[0].id` 等嵌套路徑）

批量執行時，前面接口提取的值會自動註入到後續接口。

### 斷言規則
| 類型 | 說明 |
|------|------|
| 狀態碼 | HTTP 響應碼 == 期望值 |
| JSON路徑 | 指定字段值 == 期望值 |
| 包含字符串 | 響應體包含某字符串 |
| 不為空 | 指定字段非空 |

### 加密請求（可選）
- AES-CBC：填寫 16/24/32 位密鑰
- BASE64：無需密鑰
- MD5：不可逆哈希

---

## 🔌 REST API 文檔

```
POST  /api/categories/            創建分類
GET   /api/apis/                  接口列表（支持分頁、搜索、分類過濾）
POST  /api/apis/                  創建接口
PUT   /api/apis/{id}/             更新接口
DELETE /api/apis/{id}/            刪除接口
POST  /api/apis/{id}/run/         單個執行
POST  /api/run/batch/             批量執行
GET   /api/reports/               報告列表
GET   /api/reports/{id}/          報告詳情
POST  /api/variables/token/generate/  生成Token
```

---

## 📦 依賴清單

```
Django==5.1.4
requests==2.32.3
pycryptodome==3.21.0
django-cors-headers==4.6.0
```
