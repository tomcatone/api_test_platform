# API 接口測試平台 v4

> 基於 **Django 5.1 + SQLite3** 的一站式接口測試平台，單頁應用無需前端框架，開箱即用。

---

## 目錄

- [功能總覽](#功能總覽)
- [快速啟動（Windows）](#快速啟動windows)
- [手動安裝](#手動安裝)
- [常見問題](#常見問題)
- [專案結構](#專案結構)
- [核心功能說明](#核心功能說明)
- [REST API 文件](#rest-api-文件)
- [依賴清單](#依賴清單)

---

## 功能總覽

| 模組 | 功能 |
|------|------|
| 接口管理 | 新增、編輯、分類、排序、搜尋、分頁 |
| 執行引擎 | 單次執行、背景批次執行（非阻塞）、即時進度輪詢 |
| 斷言系統 | 狀態碼、JSON 路徑、包含字串、不為空、正則、DeepDiff |
| 變數系統 | 全域變數、動態變數、跨接口提取傳值、Token 生成 |
| 壓力測試 | Locust Python API + gevent，子進程隔離，即時狀態輪詢 |
| 測試報告 | 詳細測試報告、壓測統計報告、郵件傳送、摘要導出（TXT/CSV） |
| 定時任務 | APScheduler，cron / interval 兩種模式 |
| DB 斷言 | MySQL / SQLite / PostgreSQL 前置後置 SQL 斷言 |
| Redis | 多連線管理，GET / SET / DEL / KEYS / HGET 等操作 |
| 加密支援 | AES-CBC、BASE64、MD5、mTLS 雙向 TLS 認證 |
| 多語言介面 | 繁體中文、簡體中文、English、日本語，即時切換 |

---

## 快速啟動（Windows）

### 前置條件

- 安裝 Python 3.10+（官網：https://www.python.org/downloads/）
- 安裝時**務必勾選「Add Python to PATH」**

### 一鍵啟動

```
第一步（只需一次）：雙擊 setup.bat
                    → 自動建立虛擬環境、安裝依賴、初始化資料庫

第二步：            雙擊 start.bat
                    → 瀏覽器開啟 http://127.0.0.1:8000
```

---

## 手動安裝

```bat
:: 進入專案目錄
cd api_test_platform

:: 建立虛擬環境
python -m venv venv

:: 啟用虛擬環境
venv\Scripts\activate

:: 安裝依賴
pip install -r requirements.txt

:: 初始化資料庫
python manage.py makemigrations
python manage.py migrate

:: 啟動服務
python manage.py runserver 0.0.0.0:8000
```

瀏覽器訪問：`http://127.0.0.1:8000`

> **pip 下載慢？** 使用清華映像：
> ```bat
> pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
> ```

---

## 常見問題

| 問題 | 解決方法 |
|------|----------|
| `python` 不是內部命令 | 安裝 Python 時未勾選「Add to PATH」，重新安裝並勾選 |
| pip 安裝逾時 | 使用清華映像：`pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple` |
| 埠 8000 被佔用 | 改用其他埠：`python manage.py runserver 0.0.0.0:8080` |
| 雙擊 .bat 閃退 | 右鍵 → 以系統管理員身分執行；或在 CMD 中手動執行 |
| 中文亂碼 | CMD 執行 `chcp 65001` 切換 UTF-8 |
| `venv\Scripts\activate` 報錯 | PowerShell 需執行：`Set-ExecutionPolicy RemoteSigned` |
| 壓力測試全部失敗 | 確認已安裝 locust：`pip install locust` |
| 資料庫欄位缺少錯誤 | 執行 `python manage.py migrate`；平台啟動時也會自動補欄位 |

---

## 專案結構

```
api_test_platform\
├── setup.bat                    ← Windows 一鍵安裝腳本
├── start.bat                    ← Windows 一鍵啟動腳本
├── manage.py
├── requirements.txt
├── db.sqlite3                   （執行後自動生成）
│
├── api_test_platform\
│   ├── settings.py              Django 設定
│   ├── urls.py                  根路由
│   └── wsgi.py
│
├── apps\core\
│   ├── models.py                資料模型（ApiConfig、TestReport 等）
│   ├── views.py                 REST API 視圖（全部接口邏輯）
│   ├── urls.py                  API 路由表
│   ├── executor.py              接口執行引擎（單次/批次/加密/提取）
│   ├── locust_runner.py         壓力測試模組（Locust Python API + gevent）
│   └── apps.py                  啟動時自動資料庫遷移
│
└── templates\
    └── index.html               前端單頁應用（純 HTML + Bootstrap 5）
```

---

## 核心功能說明

### 接口管理

- 支援 GET / POST / PUT / PATCH / DELETE / HEAD / OPTIONS 七種 HTTP 方法
- 接口可歸類到**分類**，並設定排序權重
- 支援 JSON Body、Form 表單、Query Params 三種請求格式
- 可設定自訂 Headers（支援 `{{變數名}}` 佔位符取值）
- **冪等性測試**：每個接口可單獨設定重複執行次數（`repeat_enabled` + `repeat_count`，最多 100 次）

---

### 全域變數與 Token

在接口的 URL、Headers、Body、Params 中，用雙大括號引用全域變數：

```
URL:     https://api.example.com/{{env}}/users/{{user_id}}
Headers: {"Authorization": "Bearer {{token}}", "X-App-Id": "{{app_id}}"}
Body:    {"username": "{{username}}", "password": "{{password}}"}
```

**Token 生成**（在全域變數頁面操作）：

| 類型 | 說明 |
|------|------|
| UUID | 標準 UUID v4，例：`550e8400-e29b-41d4-a716-446655440000` |
| HEX32 | 32 位十六進位隨機字串 |
| HEX64 | 64 位十六進位隨機字串 |
| URLSafe | URL 安全的 Base64 Token |

**動態變數**：可設定運算式，在每次執行前動態計算值（如當前時間戳、隨機數）。

---

### 斷言系統

每個接口可新增多條斷言規則，**全部通過**才算測試成功：

| 斷言類型 | 說明 | 設定範例 |
|----------|------|----------|
| 狀態碼 | HTTP 回應碼等於期望值 | 期望值：`200` |
| JSON 路徑 | 指定欄位值等於期望值 | 路徑：`data.code`，期望：`0` |
| 包含字串 | 回應體包含某字串 | `"success"` |
| 不為空 | 指定 JSON 欄位非空非 null | 路徑：`data.token` |
| 正則運算式 | 回應體符合正則 | `"id":\s*\d+` |
| DeepDiff | 與基準回應做深度差異比對 | 欄位級精確對比 |

---

### 跨接口傳值（變數提取）

在接口的「提取變數」設定中填入：

```
變數名：  token
提取路徑：data.token
```

支援巢狀路徑格式：
- `data.token`
- `data.list[0].id`
- `result.user.profile.avatar`

批次執行時，前面接口提取的值會自動注入到後續所有接口的 URL、Headers、Body。

---

### 批次執行

- 在**背景執行緒**中非阻塞執行，頁面不卡頓
- 支援「停止於首次失敗」選項
- 執行進度**每秒即時輪詢**（顯示第 X 筆 / 共 N 筆）
- 執行完成後自動生成 `TestReport`，可在報告頁面查看所有接口的詳細結果

---

### 壓力測試（Locust）

基於 **Locust Python API + gevent**，在**獨立子進程**中執行，Django 主進程完全不受 `monkey.patch_all()` 影響。

#### 安裝依賴

```bat
pip install locust
```

#### 執行流程

```
選擇接口 → 設定並發用戶數 / 生成速率 / 執行時長
         → 點擊「開始壓測」
         → 即時顯示（活躍用戶數 / 累計請求數 / 失敗數）
         → 壓測完成 → 自動收集結果 → 顯示完整報告面板
```

#### 壓測報告內容

| 區塊 | 包含指標 |
|------|----------|
| 性能評級 | A / B / C / D / F（依失敗率 + P90 自動評定，顯示於右上角） |
| KPI 卡片 | 總請求數、成功率、失敗率、RPS 吞吐量、並發用戶數、執行時長 |
| 響應時間分析 | 平均值、P50、P75、P90、P95、P99、最大值（每項附比例色條） |
| 請求結果卡 | 成功/失敗進度條、最小/平均/最大值對比格、評級說明 |
| 逐接口明細 | 每接口的請求數、失敗率（帶色標）、各百分位響應時間、RPS |
| 導出功能 | 文字摘要（.txt）、CSV 表格（含 BOM，可直接用 Excel 開啟） |

#### 性能評級標準

| 評級 | 條件 | 說明 |
|------|------|------|
| **A 優秀** | 失敗率 = 0%  且 P90 < 200ms  | 生產就緒 |
| **B 良好** | 失敗率 < 1%  且 P90 < 500ms  | 基本達標 |
| **C 一般** | 失敗率 < 5%  且 P90 < 1000ms | 需要優化 |
| **D 較差** | 失敗率 < 10% 且 P90 < 2000ms | 問題嚴重 |
| **F 不合格** | 超出以上條件 | 不可上線 |

#### 底層架構

```
Django 主進程（正常運行，不受 gevent 影響）
    │
    └─ subprocess.Popen([python, worker.py, config.json, status.json, result.json])
            │
            ├─ from locust import HttpUser, task     ← Locust 自帶 gevent
            ├─ Environment + LocalRunner             ← 純 Python API，無需 locust CLI
            ├─ runner.start(user_count=N, rate=R)    ← gevent greenlet 並發
            ├─ 每 1 秒寫入 status.json              ← Django 輪詢讀取即時狀態
            └─ 完成後寫入 result.json               ← 包含全部統計數據
```

---

### 定時任務

基於 **APScheduler**，支援兩種觸發模式：

| 模式 | 設定格式 | 範例 |
|------|----------|------|
| Cron | 標準 cron 表達式 | `0 9 * * 1-5`（週一至週五早上 9 點）|
| Interval | 每 N 分鐘執行 | 每 30 分鐘 |

- 可選擇執行哪些接口分類
- 執行完成後可自動傳送郵件報告

---

### DeepDiff 對比

對接口回應做**欄位級深度比對**，適用於回歸測試、接口版本對比：

1. 先執行一次接口，儲存基準回應
2. 後續每次執行自動與基準比對
3. 報告顯示：新增欄位 / 刪除欄位 / 值變更 / 類型變更

---

### DB 斷言（SQL）

可在接口執行前後各運行一條 SQL，並對查詢結果做斷言：

```
前置 SQL：SELECT count(*) FROM orders WHERE user_id = 1
後置 SQL：SELECT status FROM orders WHERE id = {{last_order_id}}
斷言條件：status == 'paid'
```

支援資料庫：MySQL、SQLite、PostgreSQL

---

### Redis 操作

在「Redis 工具」頁面可對多個 Redis 實例執行以下命令：

| 命令 | 說明 |
|------|------|
| GET | 取得指定 key 的字串值 |
| SET | 設定 key-value（可指定 TTL 秒數） |
| DEL | 刪除一或多個 key |
| KEYS | 模糊搜尋 key（支援 `*` 通配符） |
| HGET | 取得 Hash 類型指定欄位 |
| HSET | 設定 Hash 類型指定欄位 |
| TTL | 查詢 key 的剩餘過期時間（秒） |

---

### mTLS / SSL 憑證

支援雙向 TLS 認證（mTLS），用於需要客戶端憑證的私有 API 環境：

1. 在「SSL 憑證」頁面上傳伺服器憑證（CA 憑證，`.crt` 格式）
2. 上傳客戶端憑證（`.crt` + `.key` 一組）
3. 在接口設定中勾選對應憑證
4. 執行時自動帶入憑證進行雙向認證

---

### 郵件報告

批次測試或壓力測試完成後，可一鍵傳送 HTML 格式郵件報告：

- 報告內容：通過率、失敗接口列表、執行耗時
- 支援多個收件人（逗號分隔）
- 支援 Gmail / 企業 SMTP 郵件伺服器

**設定路徑**：「郵件設定」→ 填入 SMTP 主機、埠、帳號、密碼 → 點擊「測試連線」

---

### 多語言介面

點擊側邊欄右上方的語言名稱即可即時切換，無需重新整理頁面：

| 語言 | 代碼 |
|------|------|
| 繁體中文 | `zh-TW` |
| 簡體中文 | `zh-CN` |
| English  | `en`    |
| 日本語   | `ja`    |

語言偏好儲存於瀏覽器 `localStorage`，下次開啟自動套用。

---

## REST API 文件

所有 API 均以 `/api/` 為前綴，回應格式統一為：

```json
{
  "code": 0,
  "message": "success",
  "data": { ... }
}
```

### 接口管理

```
GET    /api/apis/                         接口列表（支援分頁、搜尋、分類篩選）
POST   /api/apis/                         新增接口
GET    /api/apis/{id}/                    接口詳情
PUT    /api/apis/{id}/                    更新接口
DELETE /api/apis/{id}/                    刪除接口
POST   /api/apis/{id}/run/                單次執行接口
```

### 批次執行

```
POST   /api/run/batch/                    啟動批次執行（背景執行緒，立即回傳 task_id）
GET    /api/run/batch/status/{task_id}/   即時查詢批次執行進度
```

### 分類管理

```
GET    /api/categories/                   分類列表
POST   /api/categories/                   新增分類
PUT    /api/categories/{id}/              更新分類
DELETE /api/categories/{id}/              刪除分類
```

### 變數管理

```
GET    /api/variables/                    全域變數列表
POST   /api/variables/                    新增 / 更新全域變數
DELETE /api/variables/{id}/               刪除全域變數
POST   /api/variables/token/generate/     生成 Token 並儲存為全域變數
GET    /api/dynamic-vars/                 動態變數列表
POST   /api/dynamic-vars/                 新增動態變數
PUT    /api/dynamic-vars/{id}/            更新動態變數
DELETE /api/dynamic-vars/{id}/            刪除動態變數
PATCH  /api/dynamic-vars/{id}/toggle/     啟用 / 停用動態變數
```

### 測試報告

```
GET    /api/reports/                      報告列表（含分頁）
GET    /api/reports/{id}/                 報告詳情（含全部測試結果）
POST   /api/email/send-report/            傳送郵件報告
```

### 壓力測試（Locust）

```
POST   /api/locust/start/                 啟動壓測（Locust Python API，子進程執行）
GET    /api/locust/status/{task_id}/      即時查詢壓測狀態與進度
GET    /api/locust/stop/{task_id}/        停止壓測子進程
POST   /api/locust/collect/{task_id}/     收集壓測結果並儲存報告
POST   /api/locust/preview/              預覽自動生成的壓測配置腳本
```

### 定時任務

```
GET    /api/scheduler/tasks/              任務列表
POST   /api/scheduler/tasks/             新增定時任務
PUT    /api/scheduler/tasks/{id}/        更新任務
DELETE /api/scheduler/tasks/{id}/        刪除任務
POST   /api/scheduler/tasks/{id}/run/    立即執行一次（不影響排程）
PATCH  /api/scheduler/tasks/{id}/toggle/ 啟用 / 停用任務
```

### DB 連線管理

```
GET    /api/db/configs/                   DB 連線列表
POST   /api/db/configs/                   新增 DB 連線設定
PUT    /api/db/configs/{id}/              更新 DB 連線設定
DELETE /api/db/configs/{id}/              刪除 DB 連線設定
POST   /api/db/configs/{id}/test/         測試 DB 連線是否正常
POST   /api/db/execute/                   執行 SQL 查詢並回傳結果
```

### Redis 連線管理

```
GET    /api/redis/configs/                Redis 連線列表
POST   /api/redis/configs/                新增 Redis 連線設定
PUT    /api/redis/configs/{id}/           更新 Redis 連線設定
DELETE /api/redis/configs/{id}/           刪除 Redis 連線設定
POST   /api/redis/configs/{id}/test/      測試 Redis 連線是否正常
POST   /api/redis/operate/                執行 Redis 命令（GET/SET/DEL/KEYS 等）
```

### SSL / mTLS 憑證

```
GET    /api/ssl/certs/                    伺服器（CA）憑證列表
POST   /api/ssl/cert/upload/              上傳 CA 憑證
DELETE /api/ssl/cert/delete/              刪除 CA 憑證
GET    /api/ssl/client-certs/             客戶端憑證列表
POST   /api/ssl/client-cert/upload/       上傳客戶端憑證（crt + key）
DELETE /api/ssl/client-cert/delete/       刪除客戶端憑證
```

### 帳號與認證

```
POST   /api/auth/login/                   登入，回傳 session cookie
POST   /api/auth/logout/                  登出
GET    /api/auth/me/                      取得目前登入使用者資訊
POST   /api/auth/change-password/         修改密碼
GET    /api/accounts/                     使用者帳號列表（管理員限定）
POST   /api/accounts/                     新增使用者帳號（管理員限定）
PUT    /api/accounts/{id}/                更新使用者資訊（管理員限定）
DELETE /api/accounts/{id}/                刪除使用者帳號（管理員限定）
```

---

## 依賴清單

| 套件 | 版本 | 用途 |
|------|------|------|
| Django | 5.1.4 | Web 框架 |
| requests | 2.32.3 | HTTP 客戶端（接口執行） |
| httpx | 0.28.1 | 非同步 HTTP 客戶端 |
| pycryptodome | 3.21.0 | AES-CBC / MD5 加密 |
| django-cors-headers | 4.6.0 | 跨域請求支援 |
| PyMySQL | 1.1.1 | MySQL 資料庫連線 |
| redis | 5.2.1 | Redis 客戶端 |
| APScheduler | 3.10.4 | 定時任務排程器 |
| deepdiff | 7.0.1 | 回應體深度比對 |
| locust | 2.32.2 | 壓力測試（內建 gevent） |

---

## 版本記錄

| 版本 | 主要更新 |
|------|----------|
| v1 | 基礎接口測試、HTTP 斷言、批次執行、測試報告 |
| v2 | mTLS 雙向認證、全 HTTP 方法支援、冪等性重複測試 |
| v3 | 多語言 i18n（4 語言）、背景批次執行輪詢、DeepDiff 對比、DB/Redis 斷言 |
| v4 | Locust 壓力測試（gevent 子進程隔離）、壓測報告視覺化、性能評級、CSV 導出 |

---

*由 API 接口測試平台自動生成　｜　如有問題請查閱上方「常見問題」章節*
