# ── Python 3.13.1 正式鏡像（基於 Debian Bookworm slim）──
FROM python:3.13.1-slim-bookworm

# 設置環境變量
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TZ=Asia/Shanghai

# 安裝系統依賴
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
        ca-certificates \
        tzdata \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime \
    && echo $TZ > /etc/timezone \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# 創建非 root 工作用戶（安全最佳實踐）
RUN groupadd --gid 1001 appgroup \
    && useradd --uid 1001 --gid appgroup --shell /bin/bash --create-home appuser

# 設置工作目錄
WORKDIR /app

# 先複製依賴文件（利用 Docker 層緩存，依賴不變時不重新安裝）
COPY --chown=appuser:appgroup requirements.txt .

# 安裝 Python 依賴
RUN pip install --upgrade pip \
    && pip install -r requirements.txt

# 複製項目代碼
COPY --chown=appuser:appgroup . .

# 切換到非 root 用戶
USER appuser

# 暴露端口（根據實際應用修改）
EXPOSE 8000

# 健康檢查
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health/ || exit 1

# 啟動命令（根據實際應用修改）
CMD ["python", "main.py"]
