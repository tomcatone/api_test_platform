"""
API 測試平台視圖層 v2
新增：DatabaseConfig CRUD、數據庫連通測試、SQL 執行工具
"""
import json
import time
import logging

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.core.paginator import Paginator
from django.db.models import Q

from .models import Category, GlobalVariable, ApiConfig, TestReport, TestResult, DatabaseConfig
from .executor import execute_api, execute_batch, reset_runtime_vars

logger = logging.getLogger(__name__)


# ─── 工具函數 ───────────────────────────────────

def success(data=None, message='操作成功', **kw):
    resp = {'code': 0, 'message': message, 'data': data}
    resp.update(kw)
    return JsonResponse(resp)

def error(message='操作失敗', code=400):
    return JsonResponse({'code': code, 'message': message, 'data': None})

def parse_body(request):
    try:
        return json.loads(request.body)
    except Exception:
        return {}

def _safe_json(text):
    try:
        return json.loads(text)
    except Exception:
        return text


# ═══════════════════════════════════════════════
#  分類 CRUD
# ═══════════════════════════════════════════════

@csrf_exempt
def category_list(request):
    if request.method == 'GET':
        cats = Category.objects.all()
        return success([{'id': c.id, 'name': c.name, 'description': c.description,
                         'api_count': c.apis.count()} for c in cats])
    elif request.method == 'POST':
        body = parse_body(request)
        name = body.get('name', '').strip()
        if not name:
            return error('分類名稱不能為空')
        if Category.objects.filter(name=name).exists():
            return error('分類名稱已存在')
        cat = Category.objects.create(name=name, description=body.get('description', ''))
        return success({'id': cat.id, 'name': cat.name}, '創建成功')

@csrf_exempt
def category_detail(request, pk):
    try:
        cat = Category.objects.get(pk=pk)
    except Category.DoesNotExist:
        return error('分類不存在', 404)
    if request.method == 'PUT':
        body = parse_body(request)
        cat.name = body.get('name', cat.name).strip()
        cat.description = body.get('description', cat.description)
        cat.save()
        return success({'id': cat.id}, '更新成功')
    elif request.method == 'DELETE':
        cat.delete()
        return success(message='刪除成功')


# ═══════════════════════════════════════════════
#  全局變量 CRUD
# ═══════════════════════════════════════════════

@csrf_exempt
def variable_list(request):
    if request.method == 'GET':
        page = int(request.GET.get('page', 1))
        page_size = int(request.GET.get('page_size', 10))
        kw = request.GET.get('keyword', '').strip()
        qs = GlobalVariable.objects.all()
        if kw:
            qs = qs.filter(Q(name__icontains=kw) | Q(description__icontains=kw))
        pager = Paginator(qs, page_size)
        pg = pager.get_page(page)
        return success({
            'total': pager.count, 'pages': pager.num_pages,
            'page': page, 'page_size': page_size,
            'items': [{'id': v.id, 'name': v.name, 'value': v.value,
                       'var_type': v.var_type, 'description': v.description,
                       'updated_at': v.updated_at.strftime('%Y-%m-%d %H:%M:%S')} for v in pg]
        })
    elif request.method == 'POST':
        body = parse_body(request)
        name = body.get('name', '').strip()
        if not name:
            return error('變量名不能為空')
        var, created = GlobalVariable.objects.update_or_create(
            name=name,
            defaults={'value': body.get('value', ''), 'var_type': body.get('var_type', 'string'),
                      'description': body.get('description', '')}
        )
        return success({'id': var.id}, '創建成功' if created else '更新成功')

@csrf_exempt
def variable_detail(request, pk):
    try:
        var = GlobalVariable.objects.get(pk=pk)
    except GlobalVariable.DoesNotExist:
        return error('變量不存在', 404)
    if request.method == 'GET':
        return success({'id': var.id, 'name': var.name, 'value': var.value,
                        'var_type': var.var_type, 'description': var.description})
    elif request.method == 'PUT':
        body = parse_body(request)
        var.name = body.get('name', var.name).strip()
        var.value = body.get('value', var.value)
        var.var_type = body.get('var_type', var.var_type)
        var.description = body.get('description', var.description)
        var.save()
        return success({'id': var.id}, '更新成功')
    elif request.method == 'DELETE':
        var.delete()
        return success(message='刪除成功')

@csrf_exempt
def generate_token(request):
    if request.method != 'POST':
        return error('方法不允許')
    body = parse_body(request)
    token_type = body.get('type', 'uuid')
    var_name   = body.get('var_name', 'token').strip()
    import secrets, uuid
    mapping = {
        'uuid':    lambda: str(uuid.uuid4()),
        'hex32':   lambda: secrets.token_hex(16),
        'hex64':   lambda: secrets.token_hex(32),
        'urlsafe': lambda: secrets.token_urlsafe(32),
        'custom':  lambda: body.get('value', '').strip(),
    }
    token_value = mapping.get(token_type, mapping['hex32'])()
    if not token_value:
        return error('Token 值不能為空')
    GlobalVariable.objects.update_or_create(
        name=var_name,
        defaults={'value': token_value, 'var_type': 'token',
                  'description': f'Token {time.strftime("%Y-%m-%d %H:%M:%S")}'}
    )
    return success({'name': var_name, 'value': token_value}, 'Token 生成並保存成功')


# ═══════════════════════════════════════════════
#  數據庫配置 CRUD
# ═══════════════════════════════════════════════

@csrf_exempt
def db_config_list(request):
    if request.method == 'GET':
        configs = DatabaseConfig.objects.all()
        return success([c.to_dict() for c in configs])
    elif request.method == 'POST':
        body = parse_body(request)
        name = body.get('name', '').strip()
        if not name:
            return error('配置名稱不能為空')
        if DatabaseConfig.objects.filter(name=name).exists():
            return error('配置名稱已存在')
        cfg = DatabaseConfig.objects.create(
            name=name,
            host=body.get('host', '127.0.0.1'),
            port=int(body.get('port', 3306)),
            username=body.get('username', ''),
            password=body.get('password', ''),
            database=body.get('database', ''),
            charset=body.get('charset', 'utf8mb4'),
            description=body.get('description', ''),
        )
        return success(cfg.to_dict(), '創建成功')

@csrf_exempt
def db_config_detail(request, pk):
    try:
        cfg = DatabaseConfig.objects.get(pk=pk)
    except DatabaseConfig.DoesNotExist:
        return error('配置不存在', 404)
    if request.method == 'GET':
        return success(cfg.to_dict(hide_pwd=False))
    elif request.method == 'PUT':
        body = parse_body(request)
        cfg.name        = body.get('name', cfg.name).strip()
        cfg.host        = body.get('host', cfg.host)
        cfg.port        = int(body.get('port', cfg.port))
        cfg.username    = body.get('username', cfg.username)
        if body.get('password', '') not in ('', '******'):
            cfg.password = body.get('password')
        cfg.database    = body.get('database', cfg.database)
        cfg.charset     = body.get('charset', cfg.charset)
        cfg.description = body.get('description', cfg.description)
        cfg.save()
        return success(cfg.to_dict(), '更新成功')
    elif request.method == 'DELETE':
        cfg.delete()
        return success(message='刪除成功')

@csrf_exempt
def db_config_test(request, pk):
    """測試數據庫連通性"""
    if request.method != 'POST':
        return error('方法不允許')
    try:
        cfg = DatabaseConfig.objects.get(pk=pk)
    except DatabaseConfig.DoesNotExist:
        return error('配置不存在', 404)
    from .db_utils import test_connection
    ok, msg = test_connection(cfg)
    return success({'connected': ok, 'message': msg}, msg)


# ═══════════════════════════════════════════════
#  SQL 執行工具（手動執行 SQL）
# ═══════════════════════════════════════════════

@csrf_exempt
def sql_execute(request):
    """
    POST /api/db/execute/
    body: { "db_id": 1, "sql": "SELECT * FROM users LIMIT 10" }
    """
    if request.method != 'POST':
        return error('方法不允許')
    body  = parse_body(request)
    db_id = body.get('db_id')
    sql   = body.get('sql', '').strip()
    if not db_id:
        return error('請選擇數據庫配置')
    if not sql:
        return error('SQL 不能為空')
    try:
        cfg = DatabaseConfig.objects.get(pk=db_id)
    except DatabaseConfig.DoesNotExist:
        return error('數據庫配置不存在')

    from .db_utils import execute_sql_statements
    result = execute_sql_statements(cfg, sql)
    return success(result, '執行完成' if result['success'] else '執行完成（部分錯誤）')


# ═══════════════════════════════════════════════
#  接口配置 CRUD
# ═══════════════════════════════════════════════

@csrf_exempt
def api_list(request):
    if request.method == 'GET':
        page      = int(request.GET.get('page', 1))
        page_size = int(request.GET.get('page_size', 10))
        kw        = request.GET.get('keyword', '').strip()
        cat_id    = request.GET.get('category_id', '').strip()
        method_f  = request.GET.get('method', '').strip()

        qs = ApiConfig.objects.select_related('category').all()
        if kw:
            qs = qs.filter(Q(name__icontains=kw) | Q(url__icontains=kw))
        if cat_id:
            qs = qs.filter(category_id=cat_id)
        if method_f:
            qs = qs.filter(method=method_f.upper())

        pager = Paginator(qs, page_size)
        pg    = pager.get_page(page)
        return success({
            'total': pager.count, 'pages': pager.num_pages,
            'page': page, 'page_size': page_size,
            'items': [_api_to_dict(a, brief=True) for a in pg]
        })
    elif request.method == 'POST':
        return _create_or_update_api(None, parse_body(request))

@csrf_exempt
def api_detail(request, pk):
    try:
        api = ApiConfig.objects.select_related('category', 'pre_sql_db', 'post_sql_db').get(pk=pk)
    except ApiConfig.DoesNotExist:
        return error('接口不存在', 404)
    if request.method == 'GET':
        return success(_api_to_dict(api, brief=False))
    elif request.method == 'PUT':
        return _create_or_update_api(api, parse_body(request))
    elif request.method == 'DELETE':
        api.delete()
        return success(message='刪除成功')


def _api_to_dict(api, brief=True):
    d = {
        'id': api.id, 'name': api.name,
        'method': api.method, 'url': api.url,
        'category_id': api.category_id,
        'category_name': api.category.name if api.category else '未分類',
        'encrypted': api.encrypted,
        'use_async': api.use_async,
        'sort_order': api.sort_order, 'description': api.description,
        'created_at': api.created_at.strftime('%Y-%m-%d %H:%M:%S'),
        'updated_at': api.updated_at.strftime('%Y-%m-%d %H:%M:%S'),
    }
    if not brief:
        d.update({
            'content_type': api.content_type,
            'body_type': api.body_type,
            'use_session': api.use_session,
            'headers': api.headers, 'params': api.params, 'body': api.body,
            'extract_vars': api.extract_vars,
            'assertions': api.assertions,
            'db_assertions': api.db_assertions,
            'deepdiff_assertions': api.deepdiff_assertions,
            'body_enc_rules': api.body_enc_rules,
            'encrypted': api.encrypted,
            'encryption_key': api.encryption_key,
            'encryption_algorithm': api.encryption_algorithm,
            'timeout': api.timeout,
            'pre_sql_db_id': api.pre_sql_db_id,
            'pre_sql': api.pre_sql,
            'post_sql_db_id': api.post_sql_db_id,
            'post_sql': api.post_sql,
            'pre_redis_rules': getattr(api, 'pre_redis_rules', '[]') or '[]',
        })
    return d


def _vj(val, default='{}'):
    if not val:
        return default
    try:
        json.loads(val)
        return val
    except Exception:
        return default


def _vjany(val, default='{}'):
    """Like _vj but also accepts raw strings (for text body)."""
    if val is None:
        return default
    s = str(val).strip()
    return s if s else default


def _create_or_update_api(api, body):
    name = body.get('name', '').strip()
    url  = body.get('url', '').strip()
    if not name:
        return error('接口名稱不能為空')
    if not url:
        return error('請求URL不能為空')

    fields = {
        'name': name, 'url': url,
        'method': body.get('method', 'GET').upper(),
        'content_type': body.get('content_type', 'json'),
        'category_id': body.get('category_id') or None,
        'headers':      _vj(body.get('headers'), '{}'),
        'params':       _vjany(body.get('params'), '{}'),   # 兼容 JSON / key=val / 純字符串
        'body':         _vjany(body.get('body'), '{}'),    # text/data模式允許非JSON字符串
        'extract_vars': _vj(body.get('extract_vars'), '[]'),
        'assertions':   _vj(body.get('assertions'), '[]'),
        'db_assertions': _vj(body.get('db_assertions'), '[]'),
        'encrypted': bool(body.get('encrypted', False)),
        'encryption_key': body.get('encryption_key', ''),
        'encryption_algorithm': body.get('encryption_algorithm', 'AES'),
        'body_enc_rules': _vj(body.get('body_enc_rules'), '[]'),
        'use_async': bool(body.get('use_async', False)),
        'use_session': bool(body.get('use_session', False)),
        'body_type': body.get('body_type', 'json'),
        'deepdiff_assertions': _vj(body.get('deepdiff_assertions'), '[]'),
        'timeout': int(body.get('timeout', 30)),
        'pre_sql_db_id': body.get('pre_sql_db_id') or None,
        'pre_sql': body.get('pre_sql', ''),
        'post_sql_db_id': body.get('post_sql_db_id') or None,
        'post_sql': body.get('post_sql', ''),
        'pre_redis_rules': _vj(body.get('pre_redis_rules'), '[]'),
        'sort_order': int(body.get('sort_order', 0)),
        'description': body.get('description', ''),
    }

    if api is None:
        api = ApiConfig.objects.create(**fields)
        msg = '創建成功'
    else:
        for k, v in fields.items():
            setattr(api, k, v)
        api.save()
        msg = '更新成功'
    return success({'id': api.id, 'name': api.name}, msg)


# ═══════════════════════════════════════════════
#  接口執行（單個）
# ═══════════════════════════════════════════════

@csrf_exempt
def api_run_single(request, pk):
    if request.method != 'POST':
        return error('方法不允許')
    try:
        api = ApiConfig.objects.select_related('pre_sql_db', 'post_sql_db').get(pk=pk)
    except ApiConfig.DoesNotExist:
        return error('接口不存在', 404)

    rd = execute_api(api, parse_body(request).get('extra_vars', {}))

    # 保存報告
    report = TestReport.objects.create(
        name=f'單測-{api.name}-{time.strftime("%H:%M:%S")}',
        status='completed', total=1,
        passed=1 if rd['status'] == 'pass' else 0,
        failed=1 if rd['status'] == 'fail' else 0,
        error=1  if rd['status'] == 'error' else 0,
        duration=rd['response_time'] / 1000,
    )
    TestResult.objects.create(
        report=report, api=api,
        api_name=rd['api_name'], url=rd['url'], method=rd['method'],
        use_async=rd['use_async'],
        request_headers=json.dumps(rd['request_headers'], ensure_ascii=False),
        request_params=json.dumps(rd['request_params'], ensure_ascii=False),
        request_body=json.dumps(rd['request_body'], ensure_ascii=False),
        response_status=rd['response_status'],
        response_headers=json.dumps(rd['response_headers'], ensure_ascii=False),
        response_body=rd['response_body'][:10000],
        response_time=rd['response_time'],
        status=rd['status'],
        error_message=rd['error_message'],
        extracted_vars=json.dumps(rd['extracted_vars'], ensure_ascii=False),
        assertion_results=json.dumps(rd['assertion_results'], ensure_ascii=False, default=str),
        db_assertion_results=json.dumps(rd['db_assertion_results'], ensure_ascii=False, default=str),
        deepdiff_results=json.dumps(rd.get('deepdiff_results', []), ensure_ascii=False, default=str),
        pre_sql_result=rd['pre_sql_result'],
        post_sql_result=rd['post_sql_result'],
    )

    return success({
        'report_id': report.id,
        'status': rd['status'],
        'use_async': rd['use_async'],
        'use_session': rd.get('use_session', False),
        'response_status': rd['response_status'],
        'response_body': rd['response_body'][:5000],
        'response_time': rd['response_time'],
        'extracted_vars': rd['extracted_vars'],
        'assertion_results': rd['assertion_results'],
        'db_assertion_results': rd['db_assertion_results'],
        'deepdiff_results': rd.get('deepdiff_results', []),
        'pre_sql_result': _safe_json(rd['pre_sql_result']) if rd['pre_sql_result'] else None,
        'post_sql_result': _safe_json(rd['post_sql_result']) if rd['post_sql_result'] else None,
        'error_message': rd['error_message'],
    }, '執行完成')


# ═══════════════════════════════════════════════
#  批量執行
# ═══════════════════════════════════════════════

@csrf_exempt
def api_run_batch(request):
    if request.method != 'POST':
        return error('方法不允許')
    body     = parse_body(request)
    api_ids  = body.get('api_ids', [])
    rep_name = body.get('report_name', '').strip()
    if not api_ids:
        return error('請選擇要執行的接口')
    report = execute_batch(api_ids, rep_name)
    if not report:
        return error('未找到有效接口')
    return success({
        'report_id': report.id, 'name': report.name,
        'total': report.total, 'passed': report.passed,
        'failed': report.failed, 'error': report.error,
        'duration': report.duration, 'pass_rate': report.pass_rate,
    }, '批量執行完成')


# ═══════════════════════════════════════════════
#  測試報告
# ═══════════════════════════════════════════════

@csrf_exempt
def report_list(request):
    page      = int(request.GET.get('page', 1))
    page_size = int(request.GET.get('page_size', 10))
    pager     = Paginator(TestReport.objects.all(), page_size)
    pg        = pager.get_page(page)
    return success({
        'total': pager.count, 'pages': pager.num_pages,
        'page': page, 'page_size': page_size,
        'items': [{
            'id': r.id, 'name': r.name, 'status': r.status,
            'total': r.total, 'passed': r.passed, 'failed': r.failed,
            'error': r.error, 'duration': r.duration,
            'pass_rate': r.pass_rate,
            'created_at': r.created_at.strftime('%Y-%m-%d %H:%M:%S'),
        } for r in pg]
    })

@csrf_exempt
def report_detail(request, pk):
    try:
        report = TestReport.objects.get(pk=pk)
    except TestReport.DoesNotExist:
        return error('報告不存在', 404)
    if request.method == 'DELETE':
        report.delete()
        return success(message='刪除成功')
    results = report.results.all()
    return success({
        'id': report.id, 'name': report.name, 'status': report.status,
        'total': report.total, 'passed': report.passed,
        'failed': report.failed, 'error': report.error,
        'duration': report.duration, 'pass_rate': report.pass_rate,
        'created_at': report.created_at.strftime('%Y-%m-%d %H:%M:%S'),
        'results': [{
            'id': r.id, 'api_name': r.api_name, 'url': r.url,
            'method': r.method, 'use_async': r.use_async,
            'response_status': r.response_status,
            'response_time': r.response_time, 'status': r.status,
            'error_message': r.error_message,
            'request_headers': _safe_json(r.request_headers),
            'request_body':    _safe_json(r.request_body),
            'response_headers': _safe_json(r.response_headers),
            'response_body':   r.response_body[:3000],
            'extracted_vars':  _safe_json(r.extracted_vars),
            'assertion_results':    _safe_json(r.assertion_results),
            'db_assertion_results': _safe_json(r.db_assertion_results),
            'deepdiff_results':     _safe_json(r.deepdiff_results),
            'pre_sql_result':  _safe_json(r.pre_sql_result) if r.pre_sql_result else None,
            'post_sql_result': _safe_json(r.post_sql_result) if r.post_sql_result else None,
        } for r in results]
    })


# ═══════════════════════════════════════════════
#  Redis 配置 CRUD
# ═══════════════════════════════════════════════

@csrf_exempt
def redis_config_list(request):
    if request.method == 'GET':
        from .models import RedisConfig
        configs = RedisConfig.objects.all()
        return success([c.to_dict() for c in configs])
    elif request.method == 'POST':
        from .models import RedisConfig
        body = parse_body(request)
        name = body.get('name', '').strip()
        if not name:
            return error('配置名稱不能為空')
        if RedisConfig.objects.filter(name=name).exists():
            return error('配置名稱已存在')
        cfg = RedisConfig.objects.create(
            name=name,
            host=body.get('host', '127.0.0.1'),
            port=int(body.get('port', 6379)),
            password=body.get('password', ''),
            db=int(body.get('db', 0)),
            description=body.get('description', ''),
        )
        return success(cfg.to_dict(), '創建成功')


@csrf_exempt
def redis_config_detail(request, pk):
    from .models import RedisConfig
    try:
        cfg = RedisConfig.objects.get(pk=pk)
    except RedisConfig.DoesNotExist:
        return error('配置不存在', 404)

    if request.method == 'GET':
        return success(cfg.to_dict(hide_pwd=False))
    elif request.method == 'PUT':
        body = parse_body(request)
        cfg.name = body.get('name', cfg.name).strip()
        cfg.host = body.get('host', cfg.host)
        cfg.port = int(body.get('port', cfg.port))
        if body.get('password', '') not in ('', '******'):
            cfg.password = body.get('password')
        cfg.db = int(body.get('db', cfg.db))
        cfg.description = body.get('description', cfg.description)
        cfg.save()
        return success(cfg.to_dict(), '更新成功')
    elif request.method == 'DELETE':
        cfg.delete()
        return success(message='刪除成功')


@csrf_exempt
def redis_config_test(request, pk):
    if request.method != 'POST':
        return error('方法不允許')
    from .models import RedisConfig
    from .redis_utils import test_connection
    try:
        cfg = RedisConfig.objects.get(pk=pk)
    except RedisConfig.DoesNotExist:
        return error('配置不存在', 404)
    ok, msg = test_connection(cfg)
    return success({'connected': ok, 'message': msg}, msg)


# ═══════════════════════════════════════════════
#  Redis 操作工具
# ═══════════════════════════════════════════════

@csrf_exempt
def redis_operate(request):
    """
    統一 Redis 操作入口
    POST /api/redis/operate/
    body: {
      redis_id: 1,
      action: "get"|"set"|"delete"|"scan"|"ttl"|"expire"|"fetch_captcha",
      key: "...",
      value: "...",
      ttl: 0,
      pattern: "*",
      keys: [],
      -- fetch_captcha 專用 --
      var_name: "captcha",
      extract_field: "code"
    }
    """
    if request.method != 'POST':
        return error('方法不允許')

    from .models import RedisConfig
    from .redis_utils import (
        redis_get, redis_set, redis_delete, redis_scan,
        redis_ttl, redis_expire, fetch_captcha_to_global
    )

    body      = parse_body(request)
    redis_id  = body.get('redis_id')
    action    = body.get('action', '').lower()

    if not redis_id:
        return error('請選擇 Redis 配置')
    if not action:
        return error('請指定操作類型')

    try:
        cfg = RedisConfig.objects.get(pk=redis_id)
    except RedisConfig.DoesNotExist:
        return error('Redis 配置不存在')

    if action == 'get':
        result = redis_get(cfg, body.get('key', ''))
    elif action == 'set':
        result = redis_set(cfg, body.get('key', ''), body.get('value', ''), body.get('ttl'))
    elif action == 'delete':
        keys = body.get('keys') or ([body.get('key')] if body.get('key') else [])
        result = redis_delete(cfg, keys)
    elif action == 'scan':
        result = redis_scan(cfg, body.get('pattern', '*'))
    elif action == 'ttl':
        result = redis_ttl(cfg, body.get('key', ''))
    elif action == 'expire':
        result = redis_expire(cfg, body.get('key', ''), body.get('ttl', 0))
    elif action == 'fetch_captcha':
        result = fetch_captcha_to_global(
            redis_id, body.get('key', ''),
            body.get('var_name', 'captcha'),
            body.get('extract_field', None),
        )
    else:
        return error(f'不支持的操作: {action}')

    msg = '操作成功' if result.get('success') else result.get('error', '操作失敗')
    return success(result, msg)


# ═══════════════════════════════════════════════
#  郵件配置 CRUD
# ═══════════════════════════════════════════════

@csrf_exempt
def email_config_list(request):
    if request.method == 'GET':
        from .models import EmailConfig
        configs = EmailConfig.objects.all()
        return success([c.to_dict() for c in configs])
    elif request.method == 'POST':
        from .models import EmailConfig
        body = parse_body(request)
        cfg = EmailConfig.objects.create(
            name=body.get('name', '默認郵件配置'),
            smtp_host=body.get('smtp_host', ''),
            smtp_port=int(body.get('smtp_port', 465)),
            use_ssl=bool(body.get('use_ssl', True)),
            use_tls=bool(body.get('use_tls', False)),
            username=body.get('username', ''),
            password=body.get('password', ''),
            from_addr=body.get('from_addr', ''),
            from_name=body.get('from_name', 'API測試平台'),
            is_active=bool(body.get('is_active', True)),
        )
        return success(cfg.to_dict(), '創建成功')


@csrf_exempt
def email_config_detail(request, pk):
    from .models import EmailConfig
    try:
        cfg = EmailConfig.objects.get(pk=pk)
    except EmailConfig.DoesNotExist:
        return error('配置不存在', 404)

    if request.method == 'GET':
        return success(cfg.to_dict(hide_pwd=False))
    elif request.method == 'PUT':
        body = parse_body(request)
        cfg.name      = body.get('name', cfg.name)
        cfg.smtp_host = body.get('smtp_host', cfg.smtp_host)
        cfg.smtp_port = int(body.get('smtp_port', cfg.smtp_port))
        cfg.use_ssl   = bool(body.get('use_ssl', cfg.use_ssl))
        cfg.use_tls   = bool(body.get('use_tls', cfg.use_tls))
        cfg.username  = body.get('username', cfg.username)
        if body.get('password', '') not in ('', '******'):
            cfg.password = body.get('password')
        cfg.from_addr = body.get('from_addr', cfg.from_addr)
        cfg.from_name = body.get('from_name', cfg.from_name)
        cfg.is_active = bool(body.get('is_active', cfg.is_active))
        cfg.save()
        return success(cfg.to_dict(), '更新成功')
    elif request.method == 'DELETE':
        cfg.delete()
        return success(message='刪除成功')


@csrf_exempt
def email_config_test(request, pk):
    """發送測試郵件"""
    if request.method != 'POST':
        return error('方法不允許')
    from .models import EmailConfig
    from .email_utils import test_email_config
    try:
        cfg = EmailConfig.objects.get(pk=pk)
    except EmailConfig.DoesNotExist:
        return error('配置不存在', 404)
    body = parse_body(request)
    to_addr = body.get('to', '').strip()
    if not to_addr:
        return error('請提供測試收件人地址')
    ok, msg = test_email_config(cfg, to_addr)
    return success({'sent': ok, 'message': msg}, msg)


# ═══════════════════════════════════════════════
#  定時任務 CRUD
# ═══════════════════════════════════════════════

@csrf_exempt
def scheduled_task_list(request):
    if request.method == 'GET':
        from .models import ScheduledTask
        from .scheduler import get_job_status
        tasks = ScheduledTask.objects.all()
        data = []
        for t in tasks:
            d = t.to_dict()
            d['scheduler_status'] = get_job_status(t.id)
            data.append(d)
        return success(data)

    elif request.method == 'POST':
        return _create_or_update_task(None, parse_body(request))


@csrf_exempt
def scheduled_task_detail(request, pk):
    from .models import ScheduledTask
    try:
        task = ScheduledTask.objects.get(pk=pk)
    except ScheduledTask.DoesNotExist:
        return error('任務不存在', 404)

    if request.method == 'GET':
        from .scheduler import get_job_status
        d = task.to_dict()
        d['scheduler_status'] = get_job_status(task.id)
        return success(d)
    elif request.method == 'PUT':
        return _create_or_update_task(task, parse_body(request))
    elif request.method == 'DELETE':
        from .scheduler import remove_task
        remove_task(task.id)
        task.delete()
        return success(message='刪除成功')


def _create_or_update_task(task, body):
    from .models import ScheduledTask
    import json
    name = body.get('name', '').strip()
    if not name:
        return error('任務名稱不能為空')

    api_ids = body.get('api_ids', [])
    if isinstance(api_ids, str):
        try:
            api_ids = json.loads(api_ids)
        except Exception:
            api_ids = []

    fields = {
        'name': name,
        'api_ids': json.dumps(api_ids),
        'trigger_type': body.get('trigger_type', 'cron'),
        'cron_expr': body.get('cron_expr', '0 9 * * *'),
        'interval_secs': int(body.get('interval_secs', 3600)),
        'report_name_tpl': body.get('report_name_tpl', '定時任務-{task}'),
        'send_email': bool(body.get('send_email', False)),
        'email_to': body.get('email_to', ''),
        'status': body.get('status', 'active'),
        'description': body.get('description', ''),
    }

    if task is None:
        task = ScheduledTask.objects.create(**fields)
        msg = '創建成功'
    else:
        for k, v in fields.items():
            setattr(task, k, v)
        task.save()
        msg = '更新成功'

    # 同步到調度器
    from .scheduler import register_task
    register_task(task)

    return success(task.to_dict(), msg)


@csrf_exempt
def scheduled_task_run_now(request, pk):
    """立即執行一次"""
    if request.method != 'POST':
        return error('方法不允許')
    from .models import ScheduledTask
    from .scheduler import trigger_task_now
    try:
        task = ScheduledTask.objects.get(pk=pk)
    except ScheduledTask.DoesNotExist:
        return error('任務不存在', 404)
    trigger_task_now(task.id)
    return success({'task_id': task.id, 'task_name': task.name}, '已觸發立即執行')


@csrf_exempt
def scheduled_task_toggle(request, pk):
    """暫停 / 恢復任務"""
    if request.method != 'POST':
        return error('方法不允許')
    from .models import ScheduledTask
    from .scheduler import register_task, remove_task
    try:
        task = ScheduledTask.objects.get(pk=pk)
    except ScheduledTask.DoesNotExist:
        return error('任務不存在', 404)
    task.status = 'paused' if task.status == 'active' else 'active'
    task.save(update_fields=['status'])
    register_task(task)
    return success({'status': task.status}, f'任務已{"暫停" if task.status == "paused" else "恢復"}')


@csrf_exempt
def send_report_email_view(request):
    """手動發送指定報告郵件"""
    if request.method != 'POST':
        return error('方法不允許')
    from .models import TestReport
    from .email_utils import send_report_email
    body      = parse_body(request)
    report_id = body.get('report_id')
    email_to  = body.get('email_to', '').strip()
    if not report_id:
        return error('請提供 report_id')
    if not email_to:
        return error('請提供收件人地址')
    try:
        report = TestReport.objects.get(pk=report_id)
    except TestReport.DoesNotExist:
        return error('報告不存在')
    to_list = [e.strip() for e in email_to.split(',') if e.strip()]
    ok, msg = send_report_email(report, to_list)
    return success({'sent': ok, 'message': msg, 'to': to_list}, msg)


# ═══════════════════════════════════════════════
#  Locust 壓測
# ═══════════════════════════════════════════════

@csrf_exempt
def locust_start(request):
    """啟動壓測"""
    if request.method != 'POST':
        return error('方法不允許')
    from .locust_runner import start_locust
    body      = parse_body(request)
    api_ids   = body.get('api_ids', [])
    users     = int(body.get('users', 10))
    spawn_rate = int(body.get('spawn_rate', 2))
    run_time  = body.get('run_time', '60s')
    task_id   = body.get('task_id', f'run_{int(time.time())}')
    if not api_ids:
        return error('請選擇接口')
    result = start_locust(task_id, api_ids, users, spawn_rate, run_time)
    return success(result, result.get('message', ''))


@csrf_exempt
def locust_status(request, task_id):
    """查詢壓測狀態"""
    from .locust_runner import get_locust_status
    return success(get_locust_status(task_id))


@csrf_exempt
def locust_stop(request, task_id):
    """停止壓測"""
    if request.method != 'POST':
        return error('方法不允許')
    from .locust_runner import stop_locust
    return success(stop_locust(task_id))


@csrf_exempt
def locust_collect(request, task_id):
    """收集壓測結果並生成報告"""
    if request.method != 'POST':
        return error('方法不允許')
    from .locust_runner import collect_locust_result
    body = parse_body(request)
    result = collect_locust_result(task_id, body.get('report_name', ''))
    return success(result, result.get('message', ''))


@csrf_exempt
def locust_preview(request):
    """預覽 Locust 腳本"""
    if request.method != 'POST':
        return error('方法不允許')
    from .locust_runner import get_script_preview
    body = parse_body(request)
    script = get_script_preview(body.get('api_ids', []))
    return success({'script': script})
