# API 接口测试平台

基于 **Django 5.1 + SQLite3** 的接口测试平台，支持 Python 3.13+。

---

## 🚀 Windows 快速启动（推荐）

### 前提条件
- 安装 Python 3.13+（官网 https://www.python.org/downloads/）
- 安装时 **勾选 "Add Python to PATH"**

### 步骤

**第一步：安装（只需执行一次）**

双击 `setup.bat` → 自动创建虚拟环境、安装依赖、初始化数据库

**第二步：启动**

双击 `start.bat` → 浏览器打开 http://127.0.0.1:8000

---

## 🖥️ 手动安装（命令提示符）

```bat
REM 进入项目目录
cd api_test_platform

REM 创建虚拟环境
python -m venv venv

REM 激活虚拟环境
venv\Scripts\activate

REM 安装依赖
pip install -r requirements.txt

REM 初始化数据库
python manage.py makemigrations
python manage.py migrate

REM 启动服务
python manage.py runserver 0.0.0.0:8000
```

浏览器访问：http://127.0.0.1:8000

---

## ⚠️ Windows 常见问题

| 问题 | 解决方法 |
|------|----------|
| `python` 不是内部命令 | Python 安装时未勾选 "Add to PATH"，重装并勾选 |
| `pip` 安装超时 | 使用国内镜像：`pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple` |
| 端口 8000 被占用 | 改用其他端口：`python manage.py runserver 0.0.0.0:8080` |
| 双击 .bat 闪退 | 右键 → 以管理员身份运行；或在 CMD 中手动执行 |
| 中文乱码 | CMD 执行 `chcp 65001` 切换 UTF-8 |
| venv\Scripts\activate 报错 | PowerShell 需执行：`Set-ExecutionPolicy RemoteSigned` |

---

## 📁 项目结构

```
api_test_platform\
├── setup.bat                ← Windows 一键安装
├── start.bat                ← Windows 一键启动
├── manage.py
├── requirements.txt
├── db.sqlite3               (运行后自动生成)
├── api_test_platform\
│   ├── settings.py
│   ├── urls.py
│   └── wsgi.py
├── apps\core\
│   ├── models.py            数据模型
│   ├── views.py             REST API 视图
│   ├── urls.py              路由
│   └── executor.py          执行引擎
└── templates\
    └── index.html           前端单页应用
```

---

## 🎯 功能说明

### 全局变量 / Token
- 生成 UUID / HEX32 / HEX64 / URLSafe Token 并保存为全局变量
- 在接口 URL、Headers、Body 中用 `{{变量名}}` 引用

```
URL:     https://api.example.com/{{env}}/user
Headers: {"Authorization": "Bearer {{token}}"}
Body:    {"user_id": "{{user_id}}"}
```

### 跨接口传值
在接口「提取变量」中配置：
- **变量名**：`token`
- **提取路径**：`data.token`（支持 `data.list[0].id` 等嵌套路径）

批量执行时，前面接口提取的值会自动注入到后续接口。

### 断言规则
| 类型 | 说明 |
|------|------|
| 状态码 | HTTP 响应码 == 期望值 |
| JSON路径 | 指定字段值 == 期望值 |
| 包含字符串 | 响应体包含某字符串 |
| 不为空 | 指定字段非空 |

### 加密请求（可选）
- AES-CBC：填写 16/24/32 位密钥
- BASE64：无需密钥
- MD5：不可逆哈希

---

## 🔌 REST API 文档

```
POST  /api/categories/            创建分类
GET   /api/apis/                  接口列表（支持分页、搜索、分类过滤）
POST  /api/apis/                  创建接口
PUT   /api/apis/{id}/             更新接口
DELETE /api/apis/{id}/            删除接口
POST  /api/apis/{id}/run/         单个执行
POST  /api/run/batch/             批量执行
GET   /api/reports/               报告列表
GET   /api/reports/{id}/          报告详情
POST  /api/variables/token/generate/  生成Token
```

---

## 📦 依赖清单

```
anyio==4.12.1
APScheduler==3.10.4
asgiref==3.11.1
blinker==1.9.0
brotli==1.2.0
certifi==2026.1.4
cffi==2.0.0
charset-normalizer==3.4.4
click==8.3.1
colorama==0.4.6
ConfigArgParse==1.7.1
deepdiff==7.0.1
Django==5.1.4
django-cors-headers==4.6.0
djangorestframework==.15.2
Flask==3.1.3
flask-cors==6.0.2
Flask-Login==0.6.3
gevent==25.9.1
geventhttpclient==2.3.7
greenlet==3.3.2
h11==0.16.0
httpcore==1.0.9
httpx==0.28.1
idna==3.11
itsdangerous==2.2.0
Jinja2==3.1.6
locust==2.32.2
MarkupSafe==3.0.3
msgpack==1.1.2
ordered-set==4.1.0
psuti==7.2.2
pycparser==3.0
pycryptodome==3.21.0
PyMySQL==1.1.1
pytz==2025.2
pywin32==311
pyzmq==27.1.0
redis==5.2.1
requests==2.32.3
six==1.17.0
```

> 如 pip 下载慢，使用清华镜像：
> ```bat
> pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
> ```
