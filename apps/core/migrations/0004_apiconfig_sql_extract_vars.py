from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0003_merge_migrations'),
    ]

    operations = [
        migrations.AddField(
            model_name='apiconfig',
            name='pre_sql_extract_vars',
            field=models.TextField(blank=True, default='[]', verbose_name='前置SQL提取變量規則 (JSON)'),
        ),
        migrations.AddField(
            model_name='apiconfig',
            name='post_sql_extract_vars',
            field=models.TextField(blank=True, default='[]', verbose_name='後置SQL提取變量規則 (JSON)'),
        ),
    ]
