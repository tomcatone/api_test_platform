"""
初始化管理員賬戶
運行：python manage.py init_admin
"""
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from apps.core.models import UserProfile


class Command(BaseCommand):
    help = '初始化默認管理員賬戶 admin / admin123'

    def handle(self, *args, **options):
        if User.objects.filter(username='admin').exists():
            self.stdout.write(self.style.WARNING('管理員賬戶已存在，跳過。'))
            return

        user = User.objects.create_user(
            username='admin',
            password='admin123',
            is_staff=True,
        )
        UserProfile.objects.create(user=user, role='admin', display_name='管理員')
        self.stdout.write(self.style.SUCCESS('✓ 管理員賬戶創建成功  admin / admin123'))
