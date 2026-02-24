"""
增量 Migration：為舊資料庫新增 mTLS 客戶端證書欄位
適用於：已有資料庫的升級場景
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0001_initial'),
    ]

    operations = [
        # mTLS 客戶端證書三個欄位
        migrations.AddField(
            model_name='apiconfig',
            name='client_cert_enabled',
            field=models.BooleanField(default=False, verbose_name='啟用客戶端證書 (mTLS)'),
        ),
        migrations.AddField(
            model_name='apiconfig',
            name='client_cert',
            field=models.CharField(blank=True, default='', max_length=500, verbose_name='客戶端證書路徑 (.pem/.crt)'),
        ),
        migrations.AddField(
            model_name='apiconfig',
            name='client_key',
            field=models.CharField(blank=True, default='', max_length=500, verbose_name='客戶端私鑰路徑 (.pem/.key)'),
        ),
        # 幂等性測試欄位
        migrations.AddField(
            model_name='apiconfig',
            name='repeat_enabled',
            field=models.BooleanField(default=False, verbose_name='啟用重複執行（幂等性測試）'),
        ),
        migrations.AddField(
            model_name='apiconfig',
            name='repeat_count',
            field=models.IntegerField(default=1, verbose_name='重複執行次數'),
        ),
    ]
