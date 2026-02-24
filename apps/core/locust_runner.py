"""
壓測模塊 — 使用 locust Python API（gevent 驅動）
- worker 腳本在獨立子進程執行，Django 主進程完全隔離
- 使用 locust.env.Environment + LocalRunner，無需 locust CLI
- 安裝依賴：pip install locust   （locust 自帶 gevent，不需單獨安裝）
"""
import json
import os
import sys
import subprocess
import tempfile
import time
import threading
import logging

logger = logging.getLogger(__name__)

_tasks = {}
_lock  = threading.Lock()

# ══════════════════════════════════════════════════════════════
# Worker 腳本 — 在子進程中執行，使用 locust Python API
# locust 內部使用 gevent，monkey-patch 在子進程中完成
# ══════════════════════════════════════════════════════════════
_WORKER_SCRIPT = '''
# locust 壓測 Worker（子進程執行）
# 使用 locust Python API，gevent 驅動，Django 主進程不受影響
import sys, json, os, time, signal

CONFIG_PATH = sys.argv[1]
STATUS_PATH = sys.argv[2]
RESULT_PATH = sys.argv[3]

with open(CONFIG_PATH, encoding="utf-8") as f:
    cfg = json.load(f)

APIS       = cfg["apis"]
USERS      = cfg["users"]
SPAWN_RATE = cfg["spawn_rate"]
DURATION   = cfg["duration"]

def write_status(status, **kw):
    try:
        d = {"status": status, "elapsed": round(time.time() - START_TIME, 1)}
        d.update(kw)
        with open(STATUS_PATH, "w", encoding="utf-8") as f:
            json.dump(d, f)
    except Exception:
        pass

START_TIME = time.time()
write_status("starting", active_users=0, total_requests=0, total_failures=0)

# ── locust imports（gevent monkey-patch 在 locust 內部完成）──
try:
    from locust import HttpUser, task, between, events
    from locust.env import Environment
    from locust.stats import stats_printer, stats_history
    from locust.log import setup_logging
    import gevent
except ImportError as e:
    write_status("error", error=f"缺少依賴: {e}  請執行: pip install locust")
    sys.exit(1)

setup_logging("WARNING", None)

# ── 動態生成 HttpUser 類 ─────────────────────────────────────
def _make_user_class(apis):
    """根據 API 配置動態生成 locust HttpUser 子類"""

    def _make_task(api):
        name      = api["name"]
        method    = api["method"].upper()
        # locust client 使用路徑，不含 host
        import re
        full_url  = api["url"]
        path_m    = re.match(r"https?://[^/]+(.*)", full_url)
        path      = path_m.group(1) if path_m else full_url
        if not path:
            path = "/"
        headers   = api.get("headers", {})
        body_type = api.get("body_type", "json")
        body      = api.get("body", {})
        params    = api.get("params", {})

        def _task(self):
            kwargs = {"headers": headers, "name": name, "catch_response": True}
            if method in ("POST", "PUT", "PATCH"):
                if body_type == "form":
                    kwargs["data"] = body
                else:
                    kwargs["json"] = body
            else:
                kwargs["params"] = params

            with getattr(self.client, method.lower())(path, **kwargs) as resp:
                if resp.status_code >= 400:
                    resp.failure(f"HTTP {resp.status_code}")
                else:
                    resp.success()

        _task.__name__ = re.sub(r"[^a-zA-Z0-9_]", "_", name)[:40]
        return _task

    # 提取 host
    import re
    host = "http://localhost:8080"
    if apis:
        m = re.match(r"(https?://[^/]+)", apis[0]["url"])
        if m:
            host = m.group(1)

    task_methods = {
        f"task_{i}": task(_make_task(api))
        for i, api in enumerate(apis)
    }
    task_methods["wait_time"] = between(0.05, 0.3)
    task_methods["host"] = host

    return type("DynamicUser", (HttpUser,), task_methods)


# ── 啟動 locust Environment ──────────────────────────────────
UserClass = _make_user_class(APIS)
env = Environment(user_classes=[UserClass], events=events)
runner = env.create_local_runner()

# 狀態更新 greenlet
import gevent

def _status_updater():
    while True:
        stats = runner.stats.total
        write_status(
            "running" if runner.user_count > 0 else "starting",
            active_users  = runner.user_count,
            total_requests = stats.num_requests,
            total_failures = stats.num_failures,
            elapsed = round(time.time() - START_TIME, 1),
        )
        gevent.sleep(1)

updater = gevent.spawn(_status_updater)

# 啟動壓測
runner.start(user_count=USERS, spawn_rate=SPAWN_RATE)
write_status("ramping", active_users=0, total_requests=0, total_failures=0)

# 等待執行完成
gevent.sleep(DURATION)
runner.stop()
updater.kill()

# ── 整合結果並寫出 ───────────────────────────────────────────
def _pct(stats_entry, p):
    try:
        return round(stats_entry.get_response_time_percentile(p / 100), 2)
    except Exception:
        return 0

all_stats = []
for name, entry in runner.stats.entries.items():
    ep_name, ep_method = name
    all_stats.append({
        "name":              ep_name,
        "method":            ep_method,
        "num_requests":      entry.num_requests,
        "num_failures":      entry.num_failures,
        "avg_response_time": round(entry.avg_response_time, 2),
        "min_response_time": round(entry.min_response_time or 0, 2),
        "max_response_time": round(entry.max_response_time or 0, 2),
        "response_times": {
            "50": _pct(entry, 50),
            "75": _pct(entry, 75),
            "90": _pct(entry, 90),
            "95": _pct(entry, 95),
            "99": _pct(entry, 99),
        },
        "total_rps": round(entry.total_rps, 2),
    })

total = runner.stats.total
elapsed = max(time.time() - START_TIME, 0.001)
all_stats.append({
    "name":              "Aggregated",
    "method":            "",
    "num_requests":      total.num_requests,
    "num_failures":      total.num_failures,
    "avg_response_time": round(total.avg_response_time, 2),
    "min_response_time": round(total.min_response_time or 0, 2),
    "max_response_time": round(total.max_response_time or 0, 2),
    "response_times": {
        "50": _pct(total, 50),
        "75": _pct(total, 75),
        "90": _pct(total, 90),
        "95": _pct(total, 95),
        "99": _pct(total, 99),
    },
    "total_rps": round(total.total_rps, 2),
})

with open(RESULT_PATH, "w", encoding="utf-8") as f:
    json.dump(all_stats, f, ensure_ascii=False)

write_status(
    "completed",
    active_users   = 0,
    total_requests = total.num_requests,
    total_failures = total.num_failures,
    elapsed        = round(time.time() - START_TIME, 1),
)
env.runner.quit()
'''


# ══════════════════════════════════════════════════════════════
# Django 側接口（與舊版完全相容）
# ══════════════════════════════════════════════════════════════

def _parse_duration(run_time: str) -> int:
    s = run_time.strip().lower()
    if s.endswith('h'): return int(s[:-1]) * 3600
    if s.endswith('m'): return int(s[:-1]) * 60
    if s.endswith('s'): return int(s[:-1])
    try: return int(s)
    except ValueError: return 60


def _subst_vars(obj, variables):
    """遞迴替換 obj（dict / list / str）中的 {{變數名}} 佔位符"""
    if isinstance(obj, dict):
        return {k: _subst_vars(v, variables) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_subst_vars(item, variables) for item in obj]
    if isinstance(obj, str):
        for k, v in variables.items():
            obj = obj.replace(f'{{{{{k}}}}}', str(v))
        return obj
    return obj


def _build_api_payload(api_configs, variables):
    result = []
    for api in api_configs:
        url = api.url
        for k, v in variables.items():
            url = url.replace(f'{{{{{k}}}}}', str(v))

        def _j(raw, default):
            try:
                parsed = json.loads(raw or default)
                # body/params 可能是 dict 或 list，都合法
                return parsed
            except Exception:
                try:
                    return json.loads(default)
                except Exception:
                    return {}

        headers = _j(api.headers, '{}')
        body    = _j(api.body,    '{}')
        params  = _j(api.params,  '{}')

        # 遞迴替換變數，支援 dict / list / 巢狀結構
        headers = _subst_vars(headers, variables)
        body    = _subst_vars(body,    variables)
        params  = _subst_vars(params,  variables)

        result.append({
            'name':      api.name,
            'method':    api.method,
            'url':       url,
            'headers':   headers,
            'body':      body,
            'params':    params,
            'body_type': getattr(api, 'body_type', 'json') or 'json',
        })
    return result


def start_locust(task_id: str, api_ids: list, users: int = 10, spawn_rate: int = 2,
                 run_time: str = '60s', headless: bool = True) -> dict:
    from apps.core.models import ApiConfig
    from apps.core.executor import load_global_vars

    apis = list(ApiConfig.objects.filter(id__in=api_ids).order_by('sort_order', 'id'))
    if not apis:
        return {'success': False, 'message': '未找到有效接口'}

    duration     = _parse_duration(run_time)
    variables    = load_global_vars()
    api_payloads = _build_api_payload(apis, variables)

    work_dir = os.path.join(tempfile.gettempdir(), 'locust_presstest')
    os.makedirs(work_dir, exist_ok=True)

    worker_path = os.path.join(work_dir, f'worker_{task_id}.py')
    config_path = os.path.join(work_dir, f'config_{task_id}.json')
    status_path = os.path.join(work_dir, f'status_{task_id}.json')
    result_path = os.path.join(work_dir, f'result_{task_id}.json')
    log_path    = os.path.join(work_dir, f'log_{task_id}.txt')

    with open(worker_path, 'w', encoding='utf-8') as f:
        f.write(_WORKER_SCRIPT)

    with open(config_path, 'w', encoding='utf-8') as f:
        json.dump({
            'apis':       api_payloads,
            'users':      users,
            'spawn_rate': spawn_rate,
            'duration':   duration,
        }, f, ensure_ascii=False)

    for p in (status_path, result_path):
        try: os.remove(p)
        except FileNotFoundError: pass

    try:
        log_fh = open(log_path, 'w', encoding='utf-8')
        proc = subprocess.Popen(
            [sys.executable, worker_path, config_path, status_path, result_path],
            stdout=log_fh,
            stderr=log_fh,
        )
    except Exception as e:
        return {'success': False, 'message': f'啟動子進程失敗: {e}'}

    with _lock:
        _tasks[task_id] = {
            'proc':        proc,
            'pid':         proc.pid,
            'status_path': status_path,
            'result_path': result_path,
            'log_path':    log_path,
            'api_ids':     api_ids,
            'users':       users,
            'run_time':    run_time,
            'duration':    duration,
            'start_time':  time.time(),
        }

    logger.info(f'[LoadTest] locust worker PID={proc.pid} task={task_id} '
                f'users={users} duration={duration}s')
    return {
        'success': True, 'pid': proc.pid, 'task_id': task_id,
        'script_path': worker_path,
        'message': f'壓測已啟動（locust/gevent，PID={proc.pid}）',
    }


def get_locust_status(task_id: str) -> dict:
    with _lock:
        info = _tasks.get(task_id)
    if not info:
        return {'found': False, 'message': '任務不存在'}

    retcode = info['proc'].poll()
    elapsed = round(time.time() - info['start_time'], 1)

    live = {}
    try:
        with open(info['status_path'], encoding='utf-8') as f:
            live = json.load(f)
    except Exception:
        pass

    if retcode is None:
        status = live.get('status', 'running')
    elif retcode == 0:
        status = 'completed'
    else:
        # 子進程異常退出 → 讀 log 取最後幾行
        status = 'error'
        try:
            with open(info['log_path'], encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
            live['error'] = ''.join(lines[-10:]).strip()
        except Exception:
            pass

    return {
        'found':          True,
        'task_id':        task_id,
        'status':         status,
        'pid':            info['pid'],
        'elapsed':        elapsed,
        'users':          info['users'],
        'run_time':       info['run_time'],
        'return_code':    retcode,
        'active_users':   live.get('active_users', 0),
        'total_requests': live.get('total_requests', 0),
        'total_failures': live.get('total_failures', 0),
        'error':          live.get('error', ''),
    }


def stop_locust(task_id: str) -> dict:
    with _lock:
        info = _tasks.get(task_id)
    if not info:
        return {'success': False, 'message': '任務不存在'}
    try:
        info['proc'].terminate()
        return {'success': True, 'message': f'已停止 PID={info["pid"]}'}
    except Exception as e:
        return {'success': False, 'message': str(e)}


def collect_locust_result(task_id: str, report_name: str = None) -> dict:
    with _lock:
        info = _tasks.get(task_id)
    if not info:
        return {'success': False, 'message': '任務不存在'}

    result_path = info['result_path']
    if not os.path.exists(result_path):
        # 嘗試讀 log 給出有用錯誤
        log_tail = ''
        try:
            with open(info['log_path'], encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
            log_tail = ''.join(lines[-5:]).strip()
        except Exception:
            pass
        msg = f'結果文件不存在，壓測可能尚未完成或出錯'
        if log_tail:
            msg += f'\n錯誤詳情：{log_tail}'
        return {'success': False, 'message': msg}

    try:
        with open(result_path, encoding='utf-8') as f:
            stats_list = json.load(f)
    except Exception as e:
        return {'success': False, 'message': f'解析結果失敗: {e}'}

    endpoints  = [s for s in stats_list if s.get('name') != 'Aggregated']
    agg        = next((s for s in stats_list if s.get('name') == 'Aggregated'), {})
    total_reqs = agg.get('num_requests', 0)
    total_fail = agg.get('num_failures', 0)
    rt         = agg.get('response_times', {})

    stats_summary = {
        'total_requests':    total_reqs,
        'total_failures':    total_fail,
        'fail_rate':         round(total_fail / total_reqs * 100, 2) if total_reqs else 0,
        'avg_response_time': agg.get('avg_response_time', 0),
        'min_response_time': agg.get('min_response_time', 0),
        'max_response_time': agg.get('max_response_time', 0),
        'p50':  rt.get('50', 0), 'p75': rt.get('75', 0),
        'p90':  rt.get('90', 0), 'p95': rt.get('95', 0), 'p99': rt.get('99', 0),
        'rps':  agg.get('total_rps', 0),
        'users':    info['users'],
        'run_time': info['run_time'],
        'per_endpoint': [
            {
                'name':    s.get('name'),    'method':  s.get('method'),
                'requests':s.get('num_requests', 0),
                'failures':s.get('num_failures', 0),
                'avg_ms':  s.get('avg_response_time', 0),
                'min_ms':  s.get('min_response_time', 0),
                'max_ms':  s.get('max_response_time', 0),
                'p50_ms':  s.get('response_times', {}).get('50', 0),
                'p90_ms':  s.get('response_times', {}).get('90', 0),
                'p99_ms':  s.get('response_times', {}).get('99', 0),
                'rps':     s.get('total_rps', 0),
            }
            for s in endpoints
        ],
    }

    from apps.core.models import TestReport, TestResult, ApiConfig
    passed = total_reqs - total_fail
    rname  = report_name or f'壓測報告-{task_id}-{time.strftime("%Y%m%d_%H%M%S")}'
    report = TestReport.objects.create(
        name=rname, status='completed',
        total=total_reqs, passed=passed,
        failed=total_fail, error=0,
        duration=float(info['duration']),
    )

    apis_map = {a.name: a for a in ApiConfig.objects.filter(id__in=info['api_ids'])}
    for ep in stats_summary['per_endpoint']:
        matched  = apis_map.get(ep['name'])
        err_rate = ep['failures'] / ep['requests'] * 100 if ep['requests'] else 0
        TestResult.objects.create(
            report=report, api=matched,
            api_name=ep['name'],
            url=matched.url if matched else ep['name'],
            method=ep.get('method', 'GET'),
            response_status=200 if err_rate == 0 else 500,
            response_time=ep['avg_ms'],
            status='pass' if err_rate == 0 else 'fail',
            error_message=(
                f"失敗率 {err_rate:.1f}% | "
                f"avg={ep['avg_ms']}ms p50={ep['p50_ms']}ms "
                f"p90={ep['p90_ms']}ms p99={ep['p99_ms']}ms | "
                f"RPS={ep['rps']}"
            ),
            request_body=json.dumps(stats_summary, ensure_ascii=False, default=str),
        )

    return {
        'success': True, 'report_id': report.id,
        'stats': stats_summary,
        'message': f'壓測報告已保存 (report_id={report.id})',
    }


def get_script_preview(api_ids: list) -> str:
    from apps.core.models import ApiConfig
    from apps.core.executor import load_global_vars

    apis = list(ApiConfig.objects.filter(id__in=api_ids).order_by('sort_order', 'id'))
    if not apis:
        return '# 未找到接口'

    variables = load_global_vars()
    payloads  = _build_api_payload(apis, variables)

    import re
    host = 'http://localhost:8080'
    if apis:
        m = re.match(r'(https?://[^/]+)', apis[0].url)
        if m:
            host = m.group(1)

    task_methods = []
    for i, p in enumerate(payloads):
        path_m = re.match(r'https?://[^/]+(.*)', p['url'])
        path   = (path_m.group(1) if path_m else p['url']) or '/'
        method = p['method'].lower()
        if method in ('post', 'put', 'patch'):
            if p['body_type'] == 'form':
                body_arg = f"data={json.dumps(p['body'], ensure_ascii=False)}"
            else:
                body_arg = f"json={json.dumps(p['body'], ensure_ascii=False)}"
        else:
            body_arg = f"params={json.dumps(p['params'], ensure_ascii=False)}"

        task_methods.append(
            f'    @task\n'
            f'    def task_{i}_{re.sub(chr(92)+"W", "_", p["name"])[:20]}(self):\n'
            f'        with self.client.{method}("{path}", {body_arg},\n'
            f'                headers={json.dumps(p["headers"], ensure_ascii=False)},\n'
            f'                name="{p["name"]}", catch_response=True) as resp:\n'
            f'            if resp.status_code >= 400: resp.failure(f"HTTP {{resp.status_code}}")\n'
            f'            else: resp.success()\n'
        )

    return (
        '# ═══ locust 壓測腳本預覽（gevent 驅動）═══\n'
        '# 安裝：pip install locust\n'
        '# 本平台使用 locust Python API 在子進程中執行，Django 主進程不受影響\n\n'
        'from locust import HttpUser, task, between\n\n'
        f'class ApiUser(HttpUser):\n'
        f'    host = "{host}"\n'
        f'    wait_time = between(0.05, 0.3)\n\n'
        + '\n'.join(task_methods)
    )
