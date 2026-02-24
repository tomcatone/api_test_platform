import logging
import os
from django.apps import AppConfig

logger = logging.getLogger(__name__)


def _auto_migrate_columns():
    """
    自動補齊資料庫缺少的欄位，無需手動執行 migrate。
    每次啟動時檢查，若欄位已存在則跳過（冪等）。
    """
    try:
        from django.db import connection

        # 需要自動補齊的欄位定義：(table, column, sql_type, default)
        COLUMNS_TO_ADD = [
            # mTLS 客戶端證書（v4 新增）
            ('core_apiconfig', 'client_cert_enabled', 'BOOLEAN NOT NULL DEFAULT 0',  None),
            ('core_apiconfig', 'client_cert',         "VARCHAR(500) NOT NULL DEFAULT ''", None),
            ('core_apiconfig', 'client_key',          "VARCHAR(500) NOT NULL DEFAULT ''", None),
            # SSL 驗證（如較舊版本缺失）
            ('core_apiconfig', 'ssl_verify', "VARCHAR(10) NOT NULL DEFAULT 'true'", None),
            ('core_apiconfig', 'ssl_cert',   "VARCHAR(500) NOT NULL DEFAULT ''",    None),
            # 前置 Redis（如較舊版本缺失）
            ('core_apiconfig', 'pre_redis_rules', "TEXT NOT NULL DEFAULT '[]'", None),
            # 幂等性測試（v4 新增）← 這兩個是當前 500 的根因
            ('core_apiconfig', 'repeat_enabled', 'BOOLEAN NOT NULL DEFAULT 0',  None),
            ('core_apiconfig', 'repeat_count',   'INTEGER NOT NULL DEFAULT 1',  None),
        ]

        with connection.cursor() as cursor:
            # 取得當前所有欄位
            cursor.execute("PRAGMA table_info(core_apiconfig)")
            existing = {row[1] for row in cursor.fetchall()}

            for table, col, col_type, _ in COLUMNS_TO_ADD:
                if col not in existing:
                    cursor.execute(f'ALTER TABLE {table} ADD COLUMN {col} {col_type}')
                    logger.info(f'[AutoMigrate] 已新增欄位: {table}.{col}')
                    existing.add(col)

        logger.info('[AutoMigrate] 欄位補齊完成')
    except Exception as ex:
        logger.warning(f'[AutoMigrate] 補齊欄位失敗（非致命）: {ex}')


class CoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.core'
    verbose_name = 'API測試平台'

    def ready(self):
        """Django 完成啟動後執行初始化"""

        # ── 自動補齊資料庫欄位（無需手動 migrate，所有啟動模式均執行）──
        # 注意：必須在 RUN_MAIN 判斷之前執行，否則 waitress/gunicorn 或
        # --noreload 模式下 RUN_MAIN 未設置，欄位補齊會被跳過
        _auto_migrate_columns()

        # RUN_MAIN=true 表示 Django reloader 的子進程，只在子進程中啟動一次
        # 排程器和初始化只在子進程執行，避免 reloader 重複啟動
        if os.environ.get('RUN_MAIN') != 'true':
            return

        # ── 啟動排程器 ──
        try:
            from apps.core import scheduler
            scheduler.start()
        except Exception as e:
            logger.warning(f'[Scheduler] 啟動跳過（非致命）: {e}')

        # ── 自動初始化管理員賬戶（首次啟動）──
        try:
            from django.contrib.auth.models import User
            from apps.core.models import UserProfile
            if not User.objects.filter(username='admin').exists():
                u = User.objects.create_user(username='admin', password='admin123', is_staff=True)
                UserProfile.objects.create(user=u, role='admin', display_name='管理員')
                logger.info('[Auth] 已自動創建管理員賬戶 admin / admin123')
        except Exception as e:
            logger.warning(f'[Auth] 初始化管理員跳過: {e}')

