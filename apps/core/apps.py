import logging
import os
from django.apps import AppConfig

logger = logging.getLogger(__name__)


class CoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.core'
    verbose_name = 'API測試平台'

    def ready(self):
        """Django 完成啟動後自動啟動 APScheduler"""
        # RUN_MAIN=true 表示 Django reloader 的子進程，只在子進程中啟動一次
        if os.environ.get('RUN_MAIN') != 'true':
            return
        try:
            from apps.core import scheduler
            scheduler.start()
        except Exception as e:
            logger.warning(f'[Scheduler] 啟動跳過（非致命）: {e}')
