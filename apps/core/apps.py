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

        # 自動初始化管理員賬戶（首次啟動）
        try:
            from django.contrib.auth.models import User
            from apps.core.models import UserProfile
            if not User.objects.filter(username='admin').exists():
                u = User.objects.create_user(username='admin', password='admin123', is_staff=True)
                UserProfile.objects.create(user=u, role='admin', display_name='管理員')
                logger.info('[Auth] 已自動創建管理員賬戶 admin / admin123')
        except Exception as e:
            logger.warning(f'[Auth] 初始化管理員跳過: {e}')
