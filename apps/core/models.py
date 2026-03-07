"""
API測試平台核心數據模型
v2: 新增 DatabaseConfig、ApiConfig 異步+SQL前後置字段
"""
import json
from django.db import models


class UserProfile(models.Model):
    """用戶擴展信息（角色管理）"""
    ROLE_CHOICES = [
        ('admin',  '管理員'),
        ('normal', '普通用戶'),
    ]
    user         = models.OneToOneField('auth.User', on_delete=models.CASCADE, related_name='profile')
    role         = models.CharField(max_length=20, choices=ROLE_CHOICES, default='normal')
    display_name = models.CharField(max_length=100, blank=True, default='')
    created_at   = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = '用戶資料'
        verbose_name_plural = '用戶資料'

    def __str__(self):
        return f'{self.user.username} ({self.get_role_display()})'

    def is_admin(self):
        return self.role == 'admin'

    def to_dict(self):
        return {
            'id':           self.user.id,
            'username':     self.user.username,
            'display_name': self.display_name or self.user.username,
            'role':         self.role,
            'role_label':   self.get_role_display(),
            'is_active':    self.user.is_active,
            'created_at':   self.user.date_joined.strftime('%Y-%m-%d %H:%M:%S'),
        }


class Category(models.Model):
    """接口分類"""
    name = models.CharField(max_length=100, unique=True, verbose_name='分類名稱')
    description = models.TextField(blank=True, default='', verbose_name='描述')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='創建時間')

    class Meta:
        verbose_name = '接口分類'
        verbose_name_plural = '接口分類'
        ordering = ['name']

    def __str__(self):
        return self.name


class GlobalVariable(models.Model):
    """全局變量 (包含Token等)"""
    VAR_TYPES = [
        ('string', '字符串'),
        ('token', 'Token'),
        ('json', 'JSON'),
    ]
    name = models.CharField(max_length=100, unique=True, verbose_name='變量名')
    value = models.TextField(verbose_name='變量值')
    var_type = models.CharField(max_length=20, choices=VAR_TYPES, default='string', verbose_name='類型')
    description = models.TextField(blank=True, default='', verbose_name='描述')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='創建時間')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新時間')

    class Meta:
        verbose_name = '全局變量'
        verbose_name_plural = '全局變量'
        ordering = ['-updated_at']

    def __str__(self):
        return f'{self.name} = {self.value[:50]}'


class DynamicVar(models.Model):
    """動態變量 — 每次接口請求前自動重新生成"""
    TYPE_CHOICES = [
        ('phone',     '🇨🇳 隨機中國手機號'),
        ('timestamp', '⏱ 當前時間戳（秒）'),
        ('timestamp_ms', '⏱ 當前時間戳（毫秒）'),
        ('datetime',  '📅 當前日期時間（yyyy-MM-dd HH:mm:ss）'),
        ('date',      '📅 當前日期（yyyy-MM-dd）'),
        ('uuid',      '🔑 隨機 UUID'),
    ]
    name        = models.CharField(max_length=100, unique=True, verbose_name='變量名（{{name}}）')
    dyn_type    = models.CharField(max_length=30, choices=TYPE_CHOICES, default='phone', verbose_name='類型')
    enabled     = models.BooleanField(default=True, verbose_name='啟用（每次請求前生成）')
    description = models.TextField(blank=True, default='', verbose_name='備註')
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = '動態變量'
        verbose_name_plural = '動態變量'
        ordering = ['name']

    def generate(self) -> str:
        """生成當次的值"""
        import random, time, uuid as uuid_mod
        from datetime import datetime
        if self.dyn_type == 'phone':
            prefixes = ['130','131','132','133','134','135','136','137','138','139',
                        '150','151','152','153','155','156','157','158','159',
                        '170','171','172','173','175','176','177','178',
                        '180','181','182','183','184','185','186','187','188','189',
                        '191','192','193','195','196','197','198','199']
            return random.choice(prefixes) + str(random.randint(10000000, 99999999))
        elif self.dyn_type == 'timestamp':
            return str(int(time.time()))
        elif self.dyn_type == 'timestamp_ms':
            return str(int(time.time() * 1000))
        elif self.dyn_type == 'datetime':
            return datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        elif self.dyn_type == 'date':
            return datetime.now().strftime('%Y-%m-%d')
        elif self.dyn_type == 'uuid':
            return str(uuid_mod.uuid4())
        return ''

    def to_dict(self):
        return {
            'id': self.id, 'name': self.name, 'dyn_type': self.dyn_type,
            'enabled': self.enabled, 'description': self.description,
            'type_label': dict(self.TYPE_CHOICES).get(self.dyn_type, self.dyn_type),
            'preview': self.generate(),
        }


class DatabaseConfig(models.Model):
    """MySQL 數據庫連接配置"""
    name        = models.CharField(max_length=100, unique=True, verbose_name='配置名稱')
    host        = models.CharField(max_length=200, default='127.0.0.1', verbose_name='主機')
    port        = models.IntegerField(default=3306, verbose_name='端口')
    username    = models.CharField(max_length=100, verbose_name='用戶名')
    password    = models.CharField(max_length=200, verbose_name='密碼')
    database    = models.CharField(max_length=100, verbose_name='數據庫名')
    charset     = models.CharField(max_length=20, default='utf8mb4', verbose_name='字符集')
    description = models.TextField(blank=True, default='', verbose_name='描述')
    created_at  = models.DateTimeField(auto_now_add=True, verbose_name='創建時間')
    updated_at  = models.DateTimeField(auto_now=True, verbose_name='更新時間')

    class Meta:
        verbose_name = '數據庫配置'
        verbose_name_plural = '數據庫配置'
        ordering = ['name']

    def __str__(self):
        return f'{self.name}  ({self.username}@{self.host}:{self.port}/{self.database})'

    def to_dict(self, hide_pwd=True):
        return {
            'id': self.id,
            'name': self.name,
            'host': self.host,
            'port': self.port,
            'username': self.username,
            'password': '******' if hide_pwd else self.password,
            'database': self.database,
            'charset': self.charset,
            'description': self.description,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            'updated_at': self.updated_at.strftime('%Y-%m-%d %H:%M:%S'),
        }


class ApiConfig(models.Model):
    """接口配置"""
    METHOD_CHOICES = [
        ('GET',     'GET'),
        ('POST',    'POST'),
        ('PUT',     'PUT'),
        ('DELETE',  'DELETE'),
        ('PATCH',   'PATCH'),
        ('HEAD',    'HEAD'),
        ('OPTIONS', 'OPTIONS'),
    ]
    CONTENT_TYPE_CHOICES = [
        ('json',      'application/json'),
        ('form',      'application/x-www-form-urlencoded'),
        ('multipart', 'multipart/form-data'),
    ]

    name         = models.CharField(max_length=200, verbose_name='接口名稱')
    category     = models.ForeignKey(
        Category, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='apis', verbose_name='所屬分類'
    )
    url          = models.TextField(verbose_name='請求URL')
    method       = models.CharField(max_length=10, choices=METHOD_CHOICES, default='GET', verbose_name='請求方式')
    content_type = models.CharField(max_length=20, choices=CONTENT_TYPE_CHOICES, default='json', verbose_name='請求類型')
    headers      = models.TextField(default='{}', verbose_name='請求頭 (JSON)')
    params       = models.TextField(default='{}', verbose_name='Query參數 (JSON)')
    body         = models.TextField(default='{}', verbose_name='請求體 json= (JSON)')

    # ── 是否使用 httpx 異步請求 ──
    use_async    = models.BooleanField(default=False, verbose_name='使用異步請求(httpx)')
    timeout      = models.IntegerField(default=30, verbose_name='超時秒數')

    # ── SSL 驗證 ──
    SSL_VERIFY_CHOICES = [
        ('true',   '驗證 SSL 證書（默認）'),
        ('false',  '跳過 SSL 驗證（忽略自簽名/內網證書）'),
        ('custom', '使用自定義 CA 證書'),
    ]
    ssl_verify  = models.CharField(max_length=10, choices=SSL_VERIFY_CHOICES, default='true', verbose_name='SSL 驗證模式')
    ssl_cert    = models.CharField(max_length=500, blank=True, default='', verbose_name='自定義 CA 證書路徑')

    # ── 客戶端證書（雙向 TLS / mTLS）──
    client_cert_enabled = models.BooleanField(default=False, verbose_name='啟用客戶端證書 (mTLS)')
    client_cert         = models.CharField(max_length=500, blank=True, default='', verbose_name='客戶端證書路徑 (.pem/.crt)')
    client_key          = models.CharField(max_length=500, blank=True, default='', verbose_name='客戶端私鑰路徑 (.pem/.key)')
    # 幂等性測試
    repeat_enabled      = models.BooleanField(default=False, verbose_name='啟用重複執行（幂等性測試）')
    repeat_count        = models.IntegerField(default=1, verbose_name='重複執行次數')

    # ── 變量提取規則 ──
    extract_vars = models.TextField(default='[]', verbose_name='提取變量規則 (JSON)')

    # ── 加密設置 ──
    encrypted            = models.BooleanField(default=False, verbose_name='啟用加密')
    encryption_key       = models.CharField(max_length=200, blank=True, default='', verbose_name='加密密鑰(raw)')
    encryption_algorithm = models.CharField(
        max_length=20, default='AES',
        choices=[('AES', 'AES-CBC'), ('AES-GCM', 'AES-GCM'), ('BASE64', 'BASE64'), ('MD5', 'MD5')],
        verbose_name='加密算法'
    )
    encryption_wrapper_key = models.CharField(
        max_length=100, blank=True, default='encrypted',
        verbose_name='全局加密JSON包裝鍵名（如 data、param、encrypted）'
    )
    # ── Body 字段級加密規則 (JSON) ──
    # 格式: [{"field":"param","ssrc":"{{payload_json}}","json_dumps":true,"key":"可選覆蓋raw"},
    #         {"field":"url","ssrc":"user/loginAndRegister"}]
    # raw 默認取 encryption_key；ssrc 支持 {{變量名}}；json_dumps=true 表示對值先 json.dumps
    body_enc_rules = models.TextField(
        default='[]', blank=True,
        verbose_name='Body字段加密規則(JSON)'
    )

    # ── HTTP 斷言規則 ──
    assertions   = models.TextField(default='[]', verbose_name='HTTP斷言規則 (JSON)')

    # ── 前置 Redis 取值（請求前從 Redis 讀取 key 存入變量）──
    # 支持多條規則，JSON 數組格式：
    # [{"redis_id":1,"key":"sms:{{mobile}}","var_name":"captcha","extract_field":"code"},...]
    pre_redis_rules = models.TextField(blank=True, default='[]', verbose_name='前置Redis取值規則(JSON)')

    # ── 數據庫前置/後置 SQL ──
    # pre_sql_db_id / post_sql_db_id: 使用哪個 DatabaseConfig (id)
    pre_sql_db   = models.ForeignKey(
        DatabaseConfig, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='pre_sql_apis', verbose_name='前置SQL數據庫'
    )
    pre_sql      = models.TextField(blank=True, default='', verbose_name='前置SQL（請求前執行）')

    post_sql_db  = models.ForeignKey(
        DatabaseConfig, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='post_sql_apis', verbose_name='後置SQL數據庫'
    )
    post_sql     = models.TextField(blank=True, default='', verbose_name='後置SQL（請求後執行）')
    pre_sql_extract_vars  = models.TextField(blank=True, default='[]', verbose_name='前置SQL提取變量規則 (JSON)')
    post_sql_extract_vars = models.TextField(blank=True, default='[]', verbose_name='後置SQL提取變量規則 (JSON)')

    # ── 數據庫斷言規則 ──
    # [{"db_id": 1, "sql": "SELECT count(*) as cnt FROM users WHERE id=1", "field": "cnt", "expected": "1", "operator": "=="}]
    db_assertions = models.TextField(default='[]', verbose_name='數據庫斷言規則 (JSON)')

    # ── DeepDiff 斷言 ──
    deepdiff_assertions = models.TextField(default='[]', verbose_name='DeepDiff斷言規則 (JSON)')

    # ── Session / body_type ──
    use_session  = models.BooleanField(default=False, verbose_name='使用Session保持會話')
    cookie          = models.TextField(blank=True, default='', verbose_name='Cookie (key=value; key2=value2)')
    request_verify   = models.TextField(blank=True, default='', verbose_name='requests verify 參數（空=默認True, false=跳過, 或CA路徑）')
    allow_redirects  = models.BooleanField(default=True, verbose_name='允許自動重定向 (allow_redirects)')

    # ── OAuth2 認證（requests-oauthlib）──
    # ── OAuth2 Authorization Code Flow（requests-oauthlib）──
    use_oauth2             = models.BooleanField(default=False, verbose_name='啟用 OAuth2 認證')
    oauth2_base_url        = models.CharField(max_length=1000, blank=True, default='', verbose_name='OAuth2 Base URL（如 https://auth.example.com）')
    oauth2_client_id       = models.CharField(max_length=500, blank=True, default='', verbose_name='OAuth2 Client ID')
    oauth2_client_secret   = models.CharField(max_length=500, blank=True, default='', verbose_name='OAuth2 Client Secret')
    oauth2_redirect_uri    = models.CharField(max_length=1000, blank=True, default='', verbose_name='OAuth2 Redirect URI')
    oauth2_scope           = models.CharField(max_length=500, blank=True, default='', verbose_name='OAuth2 Scope（空格分隔）')
    oauth2_username        = models.CharField(max_length=200, blank=True, default='', verbose_name='OAuth2 登錄用戶名')
    oauth2_password        = models.CharField(max_length=200, blank=True, default='', verbose_name='OAuth2 登錄密碼')
    oauth2_allow_redirects = models.BooleanField(default=True, verbose_name='OAuth2 請求允許重定向')
    oauth2_verify          = models.BooleanField(default=False, verbose_name='OAuth2 SSL 驗證（False=跳過自簽名憑證）')
    # 保留舊欄位（向後兼容，新版不使用）
    oauth2_token_url       = models.CharField(max_length=1000, blank=True, default='', verbose_name='[舊] OAuth2 Token URL')
    oauth2_extra_params    = models.TextField(blank=True, default='{}', verbose_name='[舊] OAuth2 額外參數 (JSON)')
    body_type    = models.CharField(
        max_length=20, default='json',
        choices=[
            ('json',   'JSON (json=)'),
            ('data',   'Data (data=)'),
            ('params', 'Params (params=)'),
            ('form',   'Form (form-urlencoded)'),
            ('text',   'Text/Plain'),
            ('raw',    'Raw'),
            ('files',  '文件上傳'),
        ],
        verbose_name='Body類型'
    )

    sort_order   = models.IntegerField(default=0, verbose_name='排序')
    description  = models.TextField(blank=True, default='', verbose_name='接口描述')
    created_at   = models.DateTimeField(auto_now_add=True, verbose_name='創建時間')
    updated_at   = models.DateTimeField(auto_now=True, verbose_name='更新時間')

    class Meta:
        verbose_name = '接口配置'
        verbose_name_plural = '接口配置'
        ordering = ['sort_order', '-created_at']

    def __str__(self):
        return f'[{self.method}] {self.name}'

    def get_headers(self):
        try: return json.loads(self.headers)
        except: return {}

    def get_params(self):
        """
        支持三種格式：
          1. JSON 對象：{"key":"val","page":"1"}  → dict
          2. key=value：key=val&page=1            → dict
          3. 純字符串：ef47c91e-xxx               → {'_raw': 'ef47c91e-xxx'}
        """
        raw = (self.params or '').strip()
        if not raw or raw == '{}':
            return {}
        # 嘗試 JSON
        try:
            result = json.loads(raw)
            if isinstance(result, dict):
                return result
        except Exception:
            pass
        # 嘗試 key=value&key2=val2
        if '=' in raw:
            try:
                from urllib.parse import parse_qs, urlencode
                parsed = parse_qs(raw, keep_blank_values=True)
                # parse_qs 返回 {key: [val]}，攤平為 {key: val}
                return {k: v[0] for k, v in parsed.items()}
            except Exception:
                pass
        # 純字符串：原樣保留，executor 會追加到 URL
        return {'_raw': raw}

    def get_body(self):
        """
        優先嘗試解析為 JSON 對象/數組。
        若不是合法 JSON（如純字符串 "10,5,20,1,33,4" 或加密後的 base64），
        則返回原始字符串，而非 {}，避免 text/plain 模式下 body 丟失。
        """
        raw = self.body or ''
        try:
            parsed = json.loads(raw)
            # json.loads("123") → 數字，json.loads('"str"') → 字符串
            # 只有 dict/list 才視為結構化 body
            if isinstance(parsed, (dict, list)):
                return parsed
            # 純字符串/數字的 JSON 表示（如 '"hello"' 或 '123'），
            # 直接返回其 Python 值（字符串或數字）
            return parsed
        except (json.JSONDecodeError, ValueError):
            # 非 JSON：如 "10,5,20,1,33,4" / "hello world"，原樣返回
            return raw

    def get_pre_redis_rules(self):
        try: return json.loads(self.pre_redis_rules)
        except: return []

    def get_extract_vars(self):
        try: return json.loads(self.extract_vars)
        except: return []

    def get_pre_sql_extract_vars(self):
        try: return json.loads(self.pre_sql_extract_vars)
        except: return []

    def get_post_sql_extract_vars(self):
        try: return json.loads(self.post_sql_extract_vars)
        except: return []

    def get_assertions(self):
        try: return json.loads(self.assertions)
        except: return []

    def get_db_assertions(self):
        try: return json.loads(self.db_assertions)
        except: return []

    def get_deepdiff_assertions(self):
        try: return json.loads(self.deepdiff_assertions)
        except: return []

    def get_body_enc_rules(self):
        try: return json.loads(self.body_enc_rules)
        except: return []


class TestReport(models.Model):
    """測試報告"""
    STATUS_CHOICES = [
        ('running',   '執行中'),
        ('completed', '已完成'),
        ('error',     '執行錯誤'),
    ]
    name      = models.CharField(max_length=200, verbose_name='報告名稱')
    status    = models.CharField(max_length=20, choices=STATUS_CHOICES, default='running', verbose_name='狀態')
    total     = models.IntegerField(default=0, verbose_name='總數')
    passed    = models.IntegerField(default=0, verbose_name='通過')
    failed    = models.IntegerField(default=0, verbose_name='失敗')
    error     = models.IntegerField(default=0, verbose_name='錯誤')
    duration  = models.FloatField(default=0.0, verbose_name='耗時(秒)')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='創建時間')

    class Meta:
        verbose_name = '測試報告'
        verbose_name_plural = '測試報告'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.name} ({self.passed}/{self.total})'

    @property
    def pass_rate(self):
        if self.total == 0:
            return 0
        return round(self.passed / self.total * 100, 1)


class TestResult(models.Model):
    """測試結果明細"""
    STATUS_CHOICES = [
        ('pass',  '通過'),
        ('fail',  '失敗'),
        ('error', '錯誤'),
    ]
    report           = models.ForeignKey(TestReport, on_delete=models.CASCADE, related_name='results')
    api              = models.ForeignKey(ApiConfig, on_delete=models.SET_NULL, null=True, blank=True, related_name='results')
    api_name         = models.CharField(max_length=200)
    url              = models.TextField()
    method           = models.CharField(max_length=10)
    request_headers  = models.TextField(default='{}')
    request_params   = models.TextField(default='{}')
    request_body     = models.TextField(default='{}')
    response_status  = models.IntegerField(default=0)
    response_headers = models.TextField(default='{}')
    response_url     = models.TextField(default='', blank=True)  # 最終響應URL（含重定向）
    response_body    = models.TextField(default='')
    response_time    = models.FloatField(default=0.0)
    status           = models.CharField(max_length=20, choices=STATUS_CHOICES)
    error_message    = models.TextField(blank=True, default='')
    extracted_vars   = models.TextField(default='{}')
    assertion_results   = models.TextField(default='[]')
    db_assertion_results = models.TextField(default='[]')   # ← 新增
    deepdiff_results     = models.TextField(default='[]')   # ← DeepDiff斷言
    pre_sql_result   = models.TextField(default='')         # ← 新增
    post_sql_result  = models.TextField(default='')         # ← 新增
    use_async        = models.BooleanField(default=False)   # ← 新增
    repeat_index     = models.IntegerField(default=0)          # 第幾次重複執行（0=第1次）
    created_at       = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = '測試結果'
        verbose_name_plural = '測試結果'
        ordering = ['repeat_index', 'created_at']

    def __str__(self):
        return f'{self.api_name} - {self.status}'


# ══════════════════════════════════════════════════════
#  Redis 配置
# ══════════════════════════════════════════════════════

class RedisConfig(models.Model):
    """Redis 連接配置"""
    name        = models.CharField(max_length=100, unique=True, verbose_name='配置名稱')
    host        = models.CharField(max_length=200, default='127.0.0.1', verbose_name='主機')
    port        = models.IntegerField(default=6379, verbose_name='端口')
    password    = models.CharField(max_length=200, blank=True, default='', verbose_name='密碼')
    db          = models.IntegerField(default=0, verbose_name='DB 索引 (0-15)')
    description = models.TextField(blank=True, default='', verbose_name='描述')
    created_at  = models.DateTimeField(auto_now_add=True, verbose_name='創建時間')
    updated_at  = models.DateTimeField(auto_now=True, verbose_name='更新時間')

    class Meta:
        verbose_name = 'Redis 配置'
        verbose_name_plural = 'Redis 配置'
        ordering = ['name']

    def __str__(self):
        return f'{self.name} ({self.host}:{self.port}/db{self.db})'

    def to_dict(self, hide_pwd=True):
        return {
            'id': self.id, 'name': self.name,
            'host': self.host, 'port': self.port,
            'password': '******' if (hide_pwd and self.password) else self.password,
            'db': self.db, 'description': self.description,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            'updated_at': self.updated_at.strftime('%Y-%m-%d %H:%M:%S'),
        }


# ══════════════════════════════════════════════════════
#  郵件配置
# ══════════════════════════════════════════════════════

class EmailConfig(models.Model):
    """SMTP 郵件配置（全局只保留一條生效配置）"""
    name       = models.CharField(max_length=100, default='默認郵件配置', verbose_name='配置名稱')
    smtp_host  = models.CharField(max_length=200, verbose_name='SMTP 主機')
    smtp_port  = models.IntegerField(default=465, verbose_name='SMTP 端口')
    use_ssl    = models.BooleanField(default=True, verbose_name='使用SSL')
    use_tls    = models.BooleanField(default=False, verbose_name='使用TLS(STARTTLS)')
    username   = models.CharField(max_length=200, verbose_name='郵箱賬號')
    password   = models.CharField(max_length=200, verbose_name='郵箱密碼/授權碼')
    from_addr  = models.CharField(max_length=200, verbose_name='發件人地址')
    from_name  = models.CharField(max_length=100, default='API測試平台', verbose_name='發件人名稱')
    is_active  = models.BooleanField(default=True, verbose_name='啟用')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='創建時間')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新時間')

    class Meta:
        verbose_name = '郵件配置'
        verbose_name_plural = '郵件配置'
        ordering = ['-is_active', '-updated_at']

    def __str__(self):
        return f'{self.name} ({self.username})'

    def to_dict(self, hide_pwd=True):
        return {
            'id': self.id, 'name': self.name,
            'smtp_host': self.smtp_host, 'smtp_port': self.smtp_port,
            'use_ssl': self.use_ssl, 'use_tls': self.use_tls,
            'username': self.username,
            'password': '******' if hide_pwd else self.password,
            'from_addr': self.from_addr, 'from_name': self.from_name,
            'is_active': self.is_active,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            'updated_at': self.updated_at.strftime('%Y-%m-%d %H:%M:%S'),
        }


# ══════════════════════════════════════════════════════
#  定時任務
# ══════════════════════════════════════════════════════

class ScheduledTask(models.Model):
    """定時執行任務"""
    TRIGGER_TYPES = [
        ('cron',     'Cron 表達式'),
        ('interval', '固定間隔'),
    ]
    STATUS_CHOICES = [
        ('active',  '運行中'),
        ('paused',  '已暫停'),
        ('stopped', '已停止'),
    ]
    name           = models.CharField(max_length=200, verbose_name='任務名稱')
    api_ids        = models.TextField(default='[]', verbose_name='接口ID列表 (JSON)')
    trigger_type   = models.CharField(max_length=20, choices=TRIGGER_TYPES, default='cron', verbose_name='觸發方式')
    # Cron: "0 9 * * 1-5"  => 週一至週五 09:00
    cron_expr      = models.CharField(max_length=100, blank=True, default='0 9 * * *', verbose_name='Cron 表達式')
    # 固定間隔: 單位秒
    interval_secs  = models.IntegerField(default=3600, verbose_name='間隔秒數')
    report_name_tpl = models.CharField(max_length=200, default='定時任務-{task}', verbose_name='報告名稱模板')
    # 郵件通知
    send_email      = models.BooleanField(default=False, verbose_name='執行後發送郵件')
    email_to        = models.TextField(blank=True, default='', verbose_name='收件人(多個逗號分隔)')
    status          = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active', verbose_name='狀態')
    last_run_at     = models.DateTimeField(null=True, blank=True, verbose_name='上次執行時間')
    last_report_id  = models.IntegerField(null=True, blank=True, verbose_name='上次報告ID')
    last_result     = models.CharField(max_length=200, blank=True, default='', verbose_name='上次結果摘要')
    description     = models.TextField(blank=True, default='', verbose_name='描述')
    created_at      = models.DateTimeField(auto_now_add=True, verbose_name='創建時間')
    updated_at      = models.DateTimeField(auto_now=True, verbose_name='更新時間')

    class Meta:
        verbose_name = '定時任務'
        verbose_name_plural = '定時任務'
        ordering = ['-created_at']

    def __str__(self):
        return self.name

    def get_api_ids(self):
        try:
            return json.loads(self.api_ids)
        except Exception:
            return []

    def get_email_to_list(self):
        return [e.strip() for e in self.email_to.split(',') if e.strip()]

    def to_dict(self):
        return {
            'id': self.id, 'name': self.name,
            'api_ids': self.get_api_ids(),
            'trigger_type': self.trigger_type,
            'cron_expr': self.cron_expr,
            'interval_secs': self.interval_secs,
            'report_name_tpl': self.report_name_tpl,
            'send_email': self.send_email,
            'email_to': self.email_to,
            'status': self.status,
            'last_run_at': self.last_run_at.strftime('%Y-%m-%d %H:%M:%S') if self.last_run_at else None,
            'last_report_id': self.last_report_id,
            'last_result': self.last_result,
            'description': self.description,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            'updated_at': self.updated_at.strftime('%Y-%m-%d %H:%M:%S'),
        }
