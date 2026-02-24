"""
API 測試平台視圖層 v2
新增：DatabaseConfig CRUD、數據庫連通測試、SQL 執行工具
"""
import json
import time
import logging
import functools

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.core.paginator import Paginator
from django.db.models import Q
from django.contrib.auth import authenticate, login as auth_login, logout as auth_logout
from django.contrib.auth.models import User
from django.shortcuts import redirect

from .models import Category, GlobalVariable, ApiConfig, TestReport, TestResult, DatabaseConfig, UserProfile
from .executor import execute_api, execute_batch, reset_runtime_vars, _batch_tasks, _batch_tasks_lock

logger = logging.getLogger(__name__)


# ─── 認證工具 ────────────────────────────────────

def require_login(view_func):
    """裝飾器：未登錄返回 401"""
    @functools.wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({'code': 401, 'message': '請先登錄', 'data': None, 'timestamp': None}, status=401)
        return view_func(request, *args, **kwargs)
    return wrapper

def require_admin(view_func):
    """裝飾器：非管理員返回 403"""
    @functools.wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({'code': 401, 'message': '請先登錄', 'data': None, 'timestamp': None}, status=401)
        profile = getattr(request.user, 'profile', None)
        if not profile or profile.role != 'admin':
            return JsonResponse({'code': 403, 'message': '需要管理員權限', 'data': None, 'timestamp': None}, status=403)
        return view_func(request, *args, **kwargs)
    return wrapper

def get_profile(user):
    """安全獲取用戶 profile"""
    try:
        return user.profile
    except Exception:
        return None


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

# ═══════════════════════════════════════════════
#  動態變量 CRUD
# ═══════════════════════════════════════════════

@csrf_exempt
def dynamic_var_list(request):
    from .models import DynamicVar
    if request.method == 'GET':
        items = [dv.to_dict() for dv in DynamicVar.objects.all()]
        return success({'items': items, 'total': len(items)})
    elif request.method == 'POST':
        body = parse_body(request)
        name = body.get('name', '').strip()
        if not name:
            return error('變量名不能為空')
        if DynamicVar.objects.filter(name=name).exists():
            return error(f'變量名 {name} 已存在')
        dv = DynamicVar.objects.create(
            name=name,
            dyn_type=body.get('dyn_type', 'phone'),
            enabled=bool(body.get('enabled', True)),
            description=body.get('description', ''),
        )
        return success(dv.to_dict(), '創建成功')

@csrf_exempt
def dynamic_var_detail(request, pk):
    from .models import DynamicVar
    try:
        dv = DynamicVar.objects.get(pk=pk)
    except DynamicVar.DoesNotExist:
        return error('不存在')
    if request.method == 'GET':
        return success(dv.to_dict())
    elif request.method == 'PUT':
        body = parse_body(request)
        dv.name        = body.get('name', dv.name).strip()
        dv.dyn_type    = body.get('dyn_type', dv.dyn_type)
        dv.enabled     = bool(body.get('enabled', dv.enabled))
        dv.description = body.get('description', dv.description)
        dv.save()
        return success(dv.to_dict(), '更新成功')
    elif request.method == 'DELETE':
        dv.delete()
        return success(message='刪除成功')

@csrf_exempt
def dynamic_var_toggle(request, pk):
    """快速切換啟用/停用"""
    from .models import DynamicVar
    if request.method != 'POST':
        return error('方法不允許')
    try:
        dv = DynamicVar.objects.get(pk=pk)
    except DynamicVar.DoesNotExist:
        return error('不存在')
    dv.enabled = not dv.enabled
    dv.save()
    return success(dv.to_dict(), f'已{"啟用" if dv.enabled else "停用"}')

@csrf_exempt
def variable_list(request):
    from .models import GlobalVariable
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

        # 只 SELECT brief 模式需要的欄位，不碰可能尚未 migrate 的新欄位
        # 即使未執行 migrate，也能正常查詢
        BRIEF_FIELDS = [
            'id','name','method','url','category_id','category',
            'encrypted','use_async','use_session',
            'sort_order','description','created_at','updated_at',
        ]
        qs = ApiConfig.objects.select_related('category').only(*BRIEF_FIELDS)
        if kw:
            qs = qs.filter(Q(name__icontains=kw) | Q(url__icontains=kw))
        if cat_id:
            qs = qs.filter(category_id=cat_id)
        if method_f:
            qs = qs.filter(method=method_f.upper())

        pager = Paginator(qs, page_size)
        pg    = pager.get_page(page)
        items = [_api_to_dict(a, brief=True) for a in pg]
        return success({
            'total': pager.count, 'pages': pager.num_pages,
            'page': page, 'page_size': page_size,
            'items': items
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


_MISSING = object()


def _safe(api, field, default=None):
    # Read from __dict__ only - avoids deferred SQL fetch and missing column errors
    val = api.__dict__.get(field, _MISSING)
    if val is _MISSING:
        return default
    return val


def _api_to_dict(api, brief=True):
    d = {
        'id': api.id, 'name': api.name,
        'method': api.method, 'url': api.url,
        'category_id': api.category_id,
        'category_name': api.category.name if api.category else '未分類',
        'encrypted':      _safe(api, 'encrypted', False),
        'use_async':      _safe(api, 'use_async', False),
        'use_session':    _safe(api, 'use_session', False),
        'repeat_enabled': bool(_safe(api, 'repeat_enabled', False)),
        'repeat_count':   int(_safe(api, 'repeat_count', 1) or 1),
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
            'ssl_verify': _safe(api, 'ssl_verify', 'true') or 'true',
            'ssl_cert':   _safe(api, 'ssl_cert', '') or '',
            'client_cert_enabled': bool(_safe(api, 'client_cert_enabled', False)),
            'client_cert':         _safe(api, 'client_cert', '') or '',
            'client_key':          _safe(api, 'client_key', '') or '',
            'pre_sql_db_id': api.pre_sql_db_id,
            'pre_sql': api.pre_sql,
            'post_sql_db_id': api.post_sql_db_id,
            'post_sql': api.post_sql,
            'pre_redis_rules': getattr(api, 'pre_redis_rules', '[]') or '[]',
            'repeat_enabled': bool(_safe(api, 'repeat_enabled', False)),
            'repeat_count':   int(_safe(api, 'repeat_count', 1) or 1),
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
        'ssl_verify': body.get('ssl_verify', 'true') or 'true',
        'ssl_cert':   body.get('ssl_cert', '') or '',
        'client_cert_enabled': bool(body.get('client_cert_enabled', False)),
        'client_cert':         body.get('client_cert', '') or '',
        'client_key':          body.get('client_key', '') or '',
        'pre_sql_db_id': body.get('pre_sql_db_id') or None,
        'pre_sql': body.get('pre_sql', ''),
        'post_sql_db_id': body.get('post_sql_db_id') or None,
        'post_sql': body.get('post_sql', ''),
        'pre_redis_rules': _vj(body.get('pre_redis_rules'), '[]'),
        'repeat_enabled': bool(body.get('repeat_enabled', False)),
        'repeat_count':   max(1, min(int(body.get('repeat_count', 1) or 1), 100)),
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

    body_data    = parse_body(request)
    extra_vars   = body_data.get('extra_vars', {})
    # 從接口配置讀取幂等性設置（在編輯頁面設定，而非執行時傳入）
    repeat_count = max(1, min(int(getattr(api, 'repeat_count', 1) or 1), 100)) if getattr(api, 'repeat_enabled', False) else 1

    # ── 多次執行（幂等性測試）──
    results_list = []
    total_time   = 0
    passed = failed = error_cnt = 0
    for i in range(repeat_count):
        rd = execute_api(api, extra_vars)
        results_list.append(rd)
        total_time += rd.get('response_time', 0)
        if rd['status'] == 'pass':   passed   += 1
        elif rd['status'] == 'fail': failed   += 1
        else:                         error_cnt += 1

    # 取最後一次結果作為主結果（展示）
    rd   = results_list[-1]
    avg_time = round(total_time / repeat_count, 2)

    # 保存報告（多次執行合併為一份報告）
    report_name = f'單測-{api.name}-x{repeat_count}-{time.strftime("%H:%M:%S")}' if repeat_count > 1 else f'單測-{api.name}-{time.strftime("%H:%M:%S")}'
    report = TestReport.objects.create(
        name=report_name,
        status='completed', total=repeat_count,
        passed=passed, failed=failed, error=error_cnt,
        duration=total_time / 1000,
    )
    # 保存每次結果
    for run_rd in results_list:
        TestResult.objects.create(
            report=report, api=api,
            api_name=run_rd['api_name'], url=run_rd['url'], method=run_rd['method'],
            use_async=run_rd['use_async'],
            request_headers=json.dumps(run_rd['request_headers'], ensure_ascii=False),
            request_params=json.dumps(run_rd['request_params'], ensure_ascii=False),
            request_body=json.dumps(run_rd['request_body'], ensure_ascii=False),
            response_status=run_rd['response_status'],
            response_headers=json.dumps(run_rd['response_headers'], ensure_ascii=False),
            response_body=run_rd['response_body'][:10000],
            response_time=run_rd['response_time'],
            status=run_rd['status'],
            error_message=run_rd['error_message'],
            extracted_vars=json.dumps(run_rd['extracted_vars'], ensure_ascii=False),
            assertion_results=json.dumps(run_rd['assertion_results'], ensure_ascii=False, default=str),
            db_assertion_results=json.dumps(run_rd['db_assertion_results'], ensure_ascii=False, default=str),
            deepdiff_results=json.dumps(run_rd.get('deepdiff_results', []), ensure_ascii=False, default=str),
            pre_sql_result=run_rd['pre_sql_result'],
            post_sql_result=run_rd['post_sql_result'],
        )

    # 多次執行摘要
    repeat_summary = None
    if repeat_count > 1:
        times_ms = [r.get('response_time', 0) for r in results_list]
        repeat_summary = {
            'total': repeat_count, 'passed': passed, 'failed': failed, 'error': error_cnt,
            'pass_rate': round(passed / repeat_count * 100, 1),
            'avg_time': avg_time,
            'min_time': min(times_ms),
            'max_time': max(times_ms),
            'statuses': [r['response_status'] for r in results_list],
            'consistent_status': len(set(r['response_status'] for r in results_list)) == 1,
            'consistent_result': len(set(r['status'] for r in results_list)) == 1,
        }

    return success({
        'report_id': report.id,
        'repeat_count': repeat_count,
        'repeat_summary': repeat_summary,
        'status': rd['status'],
        'use_async': rd['use_async'],
        'use_session': rd.get('use_session', False),
        'response_status': rd['response_status'],
        'response_body': rd['response_body'][:5000],
        'response_time': rd['response_time'],
        'avg_time': avg_time,
        'extracted_vars': rd['extracted_vars'],
        'assertion_results': rd['assertion_results'],
        'db_assertion_results': rd['db_assertion_results'],
        'deepdiff_results': rd.get('deepdiff_results', []),
        'pre_sql_result': _safe_json(rd['pre_sql_result']) if rd['pre_sql_result'] else None,
        'post_sql_result': _safe_json(rd['post_sql_result']) if rd['post_sql_result'] else None,
        'error_message': rd['error_message'],
        'enc_applied': rd.get('enc_applied', []),
        'encrypted_body': rd.get('encrypted_body'),
        'pre_redis_log': rd.get('pre_redis_log', []),
    }, f'執行完成（共 {repeat_count} 次）' if repeat_count > 1 else '執行完成')


# ═══════════════════════════════════════════════
#  批量執行
# ═══════════════════════════════════════════════

@csrf_exempt
def api_run_batch(request):
    """
    POST /api/run/batch/
    立即在後台線程啟動批量執行，返回 task_id 供輪詢
    避免長時間同步阻塞導致頁面無響應
    """
    if request.method != 'POST':
        return error('方法不允許')
    import threading, uuid as _uuid
    body            = parse_body(request)
    api_ids         = body.get('api_ids', [])
    rep_name        = body.get('report_name', '').strip()
    stop_on_failure = bool(body.get('stop_on_failure', False))
    if not api_ids:
        return error('請選擇要執行的接口')

    task_id = str(_uuid.uuid4())[:8]
    with _batch_tasks_lock:
        _batch_tasks[task_id] = {
            'status': 'running', 'progress': 0, 'total': len(api_ids),
            'report_id': None, 'error': None,
        }

    def _run():
        try:
            execute_batch(api_ids, rep_name,
                          stop_on_failure=stop_on_failure, task_id=task_id)
        except Exception as ex:
            with _batch_tasks_lock:
                if task_id in _batch_tasks:
                    _batch_tasks[task_id]['status'] = 'error'
                    _batch_tasks[task_id]['error']  = str(ex)

    threading.Thread(target=_run, daemon=True).start()
    return success({'task_id': task_id}, '批量執行已在後台啟動')


@csrf_exempt
def api_batch_status(request, task_id):
    """
    GET /api/run/batch/status/<task_id>/
    輪詢批量執行進度與結果
    """
    with _batch_tasks_lock:
        task = _batch_tasks.get(task_id)
    if not task:
        return error('任務不存在或已過期', 404)

    data = dict(task)
    # 已完成：附上報告摘要
    if task['status'] == 'completed' and task.get('report_id'):
        try:
            report = TestReport.objects.get(pk=task['report_id'])
            data['report'] = {
                'report_id': report.id, 'name': report.name,
                'total': report.total, 'passed': report.passed,
                'failed': report.failed, 'error': report.error,
                'duration': report.duration, 'pass_rate': report.pass_rate,
            }
        except TestReport.DoesNotExist:
            pass
    return success(data)


# ═══════════════════════════════════════════════
#  SSL 證書上傳
# ═══════════════════════════════════════════════

@csrf_exempt
def ssl_cert_upload(request):
    """
    上傳自定義 CA 證書文件（.pem / .crt / .cer）
    POST /api/ssl/cert/upload/
    返回：{ path: '/path/to/cert.pem', filename: 'xxx.pem' }
    """
    if request.method != 'POST':
        return error('方法不允許')
    f = request.FILES.get('cert')
    if not f:
        return error('請選擇證書文件')
    allowed_exts = {'.pem', '.crt', '.cer', '.ca-bundle', '.p7b'}
    import os
    ext = os.path.splitext(f.name)[1].lower()
    if ext not in allowed_exts:
        return error(f'不支持的文件類型 {ext}，請上傳 .pem / .crt / .cer 文件')
    if f.size > 1024 * 512:   # 512 KB 上限
        return error('證書文件不能超過 512 KB')

    # 存儲到 certs/ 目錄
    from django.conf import settings
    cert_dir = os.path.join(settings.BASE_DIR, 'certs')
    os.makedirs(cert_dir, exist_ok=True)
    import time as _t
    raw_name  = os.path.basename(f.name.replace('\\', '/'))   # 防路徑穿越
    safe_name = f'{int(_t.time())}_{raw_name.replace(" ", "_")}'
    cert_path = os.path.join(cert_dir, safe_name)
    with open(cert_path, 'wb') as fp:
        for chunk in f.chunks():
            fp.write(chunk)
    return success({'path': cert_path, 'filename': safe_name}, '證書上傳成功')


@csrf_exempt
def ssl_cert_list(request):
    """GET /api/ssl/certs/ — 列出已上傳的證書，按上傳時間降序（最新在前）"""
    import os
    from django.conf import settings
    cert_dir = os.path.join(settings.BASE_DIR, 'certs')
    if not os.path.isdir(cert_dir):
        return success({'items': []})
    items = []
    for name in os.listdir(cert_dir):
        p = os.path.join(cert_dir, name)
        if os.path.isfile(p):
            mtime = os.path.getmtime(p)
            items.append({
                'filename': name,
                'path':     p,
                'size':     os.path.getsize(p),
                'mtime':    int(mtime),            # Unix 時間戳（前端排序用）
            })
    # 按修改時間降序：最新上傳的在最前面
    items.sort(key=lambda x: x['mtime'], reverse=True)
    return success({'items': items})


@csrf_exempt
def ssl_cert_delete(request):
    """
    DELETE /api/ssl/cert/delete/
    Body: { "filename": "xxx.pem" }
    只允許刪除 certs/ 目錄內的文件，防止路徑穿越攻擊
    """
    if request.method != 'DELETE':
        return error('方法不允許')
    import os
    from django.conf import settings
    body = parse_body(request)
    filename = body.get('filename', '').strip()
    if not filename:
        return error('請提供要刪除的證書文件名')

    # 安全校驗：只允許文件名，不允許路徑分隔符（防止目錄穿越）
    if os.sep in filename or '/' in filename or '..' in filename:
        return error('非法文件名')

    cert_dir = os.path.join(settings.BASE_DIR, 'certs')
    cert_path = os.path.join(cert_dir, filename)

    # 再次確認目標路徑在 certs/ 目錄內（二次防穿越）
    real_path = os.path.realpath(cert_path)
    real_dir  = os.path.realpath(cert_dir)
    if not real_path.startswith(real_dir + os.sep):
        return error('非法路徑')

    if not os.path.isfile(real_path):
        return error(f'證書文件不存在：{filename}')

    os.remove(real_path)
    return success(message=f'證書 {filename} 已刪除')


# ═══════════════════════════════════════════════
#  客戶端證書（mTLS）管理
#  目錄：client_certs/  子目錄：certs/ key/
# ═══════════════════════════════════════════════

def _get_client_cert_dir():
    import os
    from django.conf import settings
    d = os.path.join(settings.BASE_DIR, 'client_certs')
    os.makedirs(d, exist_ok=True)
    return d


@csrf_exempt
def client_cert_upload(request):
    """
    POST /api/ssl/client-cert/upload/
    field: file=<文件>  type=cert|key
    cert 支持 .pem/.crt/.cer，key 支持 .pem/.key
    """
    if request.method != 'POST':
        return error('方法不允許')
    import os, time as _t
    f = request.FILES.get('file')
    if not f:
        return error('請選擇文件')
    file_type = request.POST.get('type', 'cert')   # 'cert' 或 'key'
    if file_type not in ('cert', 'key'):
        return error('type 必須為 cert 或 key')

    ext = os.path.splitext(f.name)[1].lower()
    if file_type == 'cert':
        allowed = {'.pem', '.crt', '.cer', '.p12', '.pfx'}
        if ext not in allowed:
            return error(f'客戶端證書不支持 {ext}，請上傳 .pem/.crt/.cer 文件')
    else:
        allowed = {'.pem', '.key', '.p8'}
        if ext not in allowed:
            return error(f'私鑰不支持 {ext}，請上傳 .pem/.key 文件')

    if f.size > 1024 * 256:  # 256 KB 上限
        return error('文件不能超過 256 KB')

    cert_dir = _get_client_cert_dir()
    subdir = os.path.join(cert_dir, file_type)  # client_certs/cert/ 或 client_certs/key/
    os.makedirs(subdir, exist_ok=True)

    raw_name = os.path.basename(f.name.replace('\\', '/'))   # 防路徑穿越：取純文件名
    safe_name = f'{int(_t.time())}_{raw_name.replace(" ", "_")}'
    save_path = os.path.join(subdir, safe_name)
    with open(save_path, 'wb') as fp:
        for chunk in f.chunks():
            fp.write(chunk)
    return success({'path': save_path, 'filename': safe_name, 'type': file_type},
                   f'{"客戶端證書" if file_type == "cert" else "私鑰"}上傳成功')


@csrf_exempt
def client_cert_list(request):
    """GET /api/ssl/client-certs/ — 列出客戶端證書和私鑰，按 mtime 降序"""
    import os
    cert_dir = _get_client_cert_dir()
    result = {'certs': [], 'keys': []}
    for kind in ('cert', 'key'):
        subdir = os.path.join(cert_dir, kind)
        if not os.path.isdir(subdir):
            continue
        items = []
        for name in os.listdir(subdir):
            p = os.path.join(subdir, name)
            if os.path.isfile(p):
                items.append({
                    'filename': name,
                    'path':     p,
                    'size':     os.path.getsize(p),
                    'mtime':    int(os.path.getmtime(p)),
                    'type':     kind,
                })
        items.sort(key=lambda x: x['mtime'], reverse=True)
        result[f'{kind}s'] = items
    return success(result)


@csrf_exempt
def client_cert_delete(request):
    """
    DELETE /api/ssl/client-cert/delete/
    Body: { "filename": "xxx.pem", "type": "cert"|"key" }
    """
    if request.method != 'DELETE':
        return error('方法不允許')
    import os
    body = parse_body(request)
    filename  = body.get('filename', '').strip()
    file_type = body.get('type', '').strip()
    if not filename:
        return error('請提供文件名')
    if file_type not in ('cert', 'key'):
        return error('type 必須為 cert 或 key')
    if os.sep in filename or '/' in filename or '..' in filename:
        return error('非法文件名')

    cert_dir  = _get_client_cert_dir()
    subdir    = os.path.join(cert_dir, file_type)
    file_path = os.path.join(subdir, filename)

    # 路徑穿越二次防禦
    real_path = os.path.realpath(file_path)
    real_dir  = os.path.realpath(subdir)
    if not real_path.startswith(real_dir + os.sep):
        return error('非法路徑')

    if not os.path.isfile(real_path):
        return error(f'文件不存在：{filename}')
    os.remove(real_path)
    return success(message=f'{"客戶端證書" if file_type == "cert" else "私鑰"} {filename} 已刪除')


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

# ═══════════════════════════════════════════════
#  認證 — 登錄 / 登出 / 當前用戶
# ═══════════════════════════════════════════════

@csrf_exempt
def auth_login_view(request):
    if request.method == 'POST':
        body = parse_body(request)
        username = body.get('username', '').strip()
        password = body.get('password', '')
        user = authenticate(request, username=username, password=password)
        if user is None:
            return error('用戶名或密碼錯誤')
        if not user.is_active:
            return error('賬戶已被停用，請聯繫管理員')
        auth_login(request, user)
        profile = get_profile(user)
        return success({
            'username':     user.username,
            'display_name': profile.display_name if profile else user.username,
            'role':         profile.role if profile else 'normal',
        }, '登錄成功')
    return error('方法不允許')


@csrf_exempt
def auth_logout_view(request):
    auth_logout(request)
    return success(message='已登出')


@csrf_exempt
def auth_me(request):
    if not request.user.is_authenticated:
        return error('未登錄', code=401)
    profile = get_profile(request.user)
    return success({
        'username':     request.user.username,
        'display_name': profile.display_name if profile else request.user.username,
        'role':         profile.role if profile else 'normal',
    })


@csrf_exempt
def auth_change_password(request):
    """修改自己的密碼"""
    if not request.user.is_authenticated:
        return JsonResponse({'code': 401, 'message': '未登錄', 'data': None, 'timestamp': None})
    if request.method != 'POST':
        return error('方法不允許')
    body = parse_body(request)
    old_pwd = body.get('old_password', '')
    new_pwd = body.get('new_password', '').strip()
    if not new_pwd or len(new_pwd) < 6:
        return error('新密碼長度不能少於 6 位')
    user = authenticate(request, username=request.user.username, password=old_pwd)
    if user is None:
        return error('原密碼不正確')
    user.set_password(new_pwd)
    user.save()
    auth_login(request, user)   # 重新登錄維持 session
    return success(message='密碼已修改')


# ═══════════════════════════════════════════════
#  賬戶管理（僅管理員）
# ═══════════════════════════════════════════════

@csrf_exempt
@require_admin
def account_list(request):
    if request.method == 'GET':
        profiles = UserProfile.objects.select_related('user').all().order_by('user__date_joined')
        return success({
            'items': [p.to_dict() for p in profiles],
            'total': profiles.count(),
        })
    elif request.method == 'POST':
        body = parse_body(request)
        username = body.get('username', '').strip()
        password = body.get('password', '').strip()
        role     = body.get('role', 'normal')
        display_name = body.get('display_name', '').strip()

        if not username:
            return error('用戶名不能為空')
        if not password or len(password) < 6:
            return error('密碼長度不能少於 6 位')
        if User.objects.filter(username=username).exists():
            return error(f'用戶名 {username} 已存在')
        if role not in ('admin', 'normal'):
            role = 'normal'

        user = User.objects.create_user(username=username, password=password)
        profile = UserProfile.objects.create(user=user, role=role, display_name=display_name or username)
        return success(profile.to_dict(), '創建成功')


@csrf_exempt
@require_admin
def account_detail(request, pk):
    try:
        user = User.objects.get(pk=pk)
        profile = user.profile
    except (User.DoesNotExist, UserProfile.DoesNotExist):
        return error('用戶不存在')

    if request.method == 'GET':
        return success(profile.to_dict())

    elif request.method == 'PUT':
        body = parse_body(request)
        # 不允許修改 admin 自己的角色
        if user.username == 'admin' and body.get('role') == 'normal':
            return error('不能修改 admin 賬戶的角色')

        # 如果提交了新用戶名，校驗唯一性
        new_username = body.get('username', '').strip()
        if new_username and new_username != user.username:
            if User.objects.exclude(pk=pk).filter(username=new_username).exists():
                return error(f'用戶名 {new_username} 已被使用')
            user.username = new_username
            user.save()

        new_pwd = body.get('password', '').strip()
        if new_pwd:
            if len(new_pwd) < 6:
                return error('密碼長度不能少於 6 位')
            user.set_password(new_pwd)
            user.save()

        profile.role         = body.get('role', profile.role)
        profile.display_name = body.get('display_name', profile.display_name).strip()
        profile.save()

        is_active = body.get('is_active')
        if is_active is not None and user.username != 'admin':
            user.is_active = bool(is_active)
            user.save()

        return success(profile.to_dict(), '更新成功')

    elif request.method == 'DELETE':
        if user.username == 'admin':
            return error('不能刪除 admin 賬戶')
        user.delete()
        return success(message='刪除成功')
