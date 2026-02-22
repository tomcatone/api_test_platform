from django.db import models
import json


class ApiCategory(models.Model):
    """接口分類"""
    name = models.CharField(max_length=100, verbose_name='分類名稱')
    description = models.TextField(blank=True, verbose_name='描述')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='創建時間')

    class Meta:
        verbose_name = '接口分類'
        verbose_name_plural = '接口分類'
        ordering = ['-created_at']

    def __str__(self):
        return self.name


class GlobalVariable(models.Model):
    """全局變量 / Token"""
    TYPE_CHOICES = [
        ('token', 'Token認證'),
        ('variable', '普通變量'),
    ]
    key = models.CharField(max_length=200, unique=True, verbose_name='變量名')
    value = models.TextField(verbose_name='變量值')
    var_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default='variable', verbose_name='類型')
    description = models.TextField(blank=True, verbose_name='描述')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = '全局變量'
        verbose_name_plural = '全局變量'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.key} = {self.value[:50]}'


class ApiConfig(models.Model):
    """接口配置"""
    METHOD_CHOICES = [
        ('GET', 'GET'),
        ('POST', 'POST'),
        ('PUT', 'PUT'),
        ('DELETE', 'DELETE'),
        ('PATCH', 'PATCH'),
    ]
    AUTH_CHOICES = [
        ('none', '不加密'),
        ('bearer', 'Bearer Token'),
        ('basic', 'Basic Auth'),
        ('api_key', 'API Key'),
        ('custom', '自定義Header'),
    ]

    name = models.CharField(max_length=200, verbose_name='接口名稱')
    category = models.ForeignKey(ApiCategory, on_delete=models.SET_NULL, null=True, blank=True,
                                  related_name='apis', verbose_name='分類')
    url = models.CharField(max_length=500, verbose_name='請求URL')
    method = models.CharField(max_length=10, choices=METHOD_CHOICES, default='GET', verbose_name='請求方法')
    headers = models.TextField(blank=True, default='{}', verbose_name='請求頭(JSON)')
    params = models.TextField(blank=True, default='{}', verbose_name='Query參數(JSON)')
    body = models.TextField(blank=True, default='{}', verbose_name='請求體(JSON)')
    body_type = models.CharField(max_length=20, default='json',
                                  choices=[('json', 'JSON'), ('form', 'Form-data'), ('raw', 'Raw')],
                                  verbose_name='Body類型')

    # 加密認證（非必選）
    auth_type = models.CharField(max_length=20, choices=AUTH_CHOICES, default='none', verbose_name='認證類型')
    auth_value = models.TextField(blank=True, verbose_name='認證值（支持{{變量名}}引用）')

    # 響應提取規則
    extract_rules = models.TextField(blank=True, default='[]',
                                      verbose_name='提取規則(JSON Array)')
    # 示例: [{"var_name": "token", "json_path": "data.token", "save_as_global": true}]

    # 斷言規則
    assert_rules = models.TextField(blank=True, default='[]', verbose_name='斷言規則(JSON Array)')
    # 示例: [{"field": "code", "operator": "eq", "expected": 200}]

    description = models.TextField(blank=True, verbose_name='描述')
    is_active = models.BooleanField(default=True, verbose_name='是否啓用')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='創建時間')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新時間')

    class Meta:
        verbose_name = '接口配置'
        verbose_name_plural = '接口配置'
        ordering = ['-created_at']

    def __str__(self):
        return f'[{self.method}] {self.name}'

    def get_extract_rules(self):
        try:
            return json.loads(self.extract_rules) if self.extract_rules else []
        except:
            return []

    def get_assert_rules(self):
        try:
            return json.loads(self.assert_rules) if self.assert_rules else []
        except:
            return []

    def get_headers(self):
        try:
            return json.loads(self.headers) if self.headers else {}
        except:
            return {}

    def get_params(self):
        try:
            return json.loads(self.params) if self.params else {}
        except:
            return {}

    def get_body(self):
        try:
            return json.loads(self.body) if self.body else {}
        except:
            return {}


class TestSuite(models.Model):
    """測試套件（用於批量執行）"""
    name = models.CharField(max_length=200, verbose_name='套件名稱')
    description = models.TextField(blank=True, verbose_name='描述')
    apis = models.ManyToManyField(ApiConfig, through='TestSuiteApi', verbose_name='接口列表')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = '測試套件'
        verbose_name_plural = '測試套件'
        ordering = ['-created_at']

    def __str__(self):
        return self.name


class TestSuiteApi(models.Model):
    """測試套件與接口的關聯"""
    suite = models.ForeignKey(TestSuite, on_delete=models.CASCADE)
    api = models.ForeignKey(ApiConfig, on_delete=models.CASCADE)
    order = models.IntegerField(default=0, verbose_name='執行順序')

    class Meta:
        ordering = ['order']


class TestReport(models.Model):
    """測試報告"""
    STATUS_CHOICES = [
        ('running', '執行中'),
        ('passed', '通過'),
        ('failed', '失敗'),
        ('error', '錯誤'),
    ]
    name = models.CharField(max_length=200, verbose_name='報告名稱')
    suite = models.ForeignKey(TestSuite, on_delete=models.SET_NULL, null=True, blank=True,
                               verbose_name='測試套件')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='running', verbose_name='狀態')
    total = models.IntegerField(default=0, verbose_name='總數')
    passed = models.IntegerField(default=0, verbose_name='通過')
    failed = models.IntegerField(default=0, verbose_name='失敗')
    duration = models.FloatField(default=0, verbose_name='耗時(秒)')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='執行時間')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = '測試報告'
        verbose_name_plural = '測試報告'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.name} - {self.status}'

    @property
    def pass_rate(self):
        if self.total == 0:
            return 0
        return round(self.passed / self.total * 100, 1)


class TestResult(models.Model):
    """單個接口測試結果"""
    report = models.ForeignKey(TestReport, on_delete=models.CASCADE,
                                related_name='results', verbose_name='測試報告')
    api_config = models.ForeignKey(ApiConfig, on_delete=models.SET_NULL,
                                    null=True, verbose_name='接口配置')
    api_name = models.CharField(max_length=200, verbose_name='接口名稱（快照）')
    api_url = models.CharField(max_length=500, verbose_name='請求URL（快照）')
    api_method = models.CharField(max_length=10, verbose_name='請求方法（快照）')
    request_headers = models.TextField(blank=True, default='{}', verbose_name='實際請求頭')
    request_body = models.TextField(blank=True, verbose_name='實際請求體')
    status_code = models.IntegerField(null=True, blank=True, verbose_name='響應狀態碼')
    response_body = models.TextField(blank=True, verbose_name='響應體')
    response_time = models.FloatField(default=0, verbose_name='響應時間(ms)')
    passed = models.BooleanField(default=False, verbose_name='是否通過')
    error_message = models.TextField(blank=True, verbose_name='錯誤信息')
    extracted_values = models.TextField(blank=True, default='{}', verbose_name='提取的值')
    assert_details = models.TextField(blank=True, default='[]', verbose_name='斷言詳情')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = '測試結果'
        verbose_name_plural = '測試結果'
        ordering = ['created_at']

    def __str__(self):
        status = '✓' if self.passed else '✗'
        return f'{status} {self.api_name}'
