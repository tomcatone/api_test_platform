"""
Merge Migration：解決 0002_add_mtls_fields 與用戶現有 0011 migration 的衝突
由 python manage.py makemigrations --merge 等效生成
"""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0002_add_mtls_fields'),
        ('core', '0011_alter_apiconfig_options_alter_category_options_and_more'),
    ]

    operations = [
    ]
