"""
gevent 壓測模塊（替代 Locust）
- 使用 gevent greenlet 實現高並發，不依賴 Locust
- worker 腳本在獨立子進程執行 monkey.patch_all()，Django 主進程完全隔離
- 接口：start / status / stop / collect / preview，與原 Locust 接口完全相容
"""
import json
import os
import sys
import tempfile
import time
import threading
import logging

logger = logging.getLogger(__name__)

# ── 全局進程追蹤 ──────────────────────────────────────────
_tasks = {}
_lock  = threading.Lock()

# ── Worker 腳本（寫入臨時文件，在子進程執行）─────────────
_WORKER_SCRIPT = r"""
import gevent.monkey
gevent.monkey.patch_all()

import gevent
import gevent.pool
import gevent.event
import gevent.lock
import requests
import json, os, sys, time, math, signal, statistics
from collections import defaultdict

CONFIG_PATH = sys.argv[1]
STATUS_PATH = sys.argv[2]
RESULT_PATH = sys.argv[3]

with open(CONFIG_PATH, encoding='utf-8') as f:
    cfg = json.load(f)

APIS       = cfg['apis']
USERS      = cfg['users']
SPAWN_RATE = cfg['spawn_rate']
DURATION   = cfg['duration']
WAIT_MIN   = cfg.get('wait_min', 0.05)
WAIT_MAX   = cfg.get('wait_max', 0.3)

_stats_lock  = gevent.lock.RLock()
_stats       = defaultdict(lambda: {'num_requests':0,'num_failures':0,'response_times':[],'method':'','name':''})
_stop_event  = gevent.event.Event()
_start_time  = time.time()
_active      = [0]

def _write_status(status, **extra):
    try:
        data = {'status':status,'elapsed':round(time.time()-_start_time,1),
                'active_users':_active[0],
                'total_requests':sum(v['num_requests'] for v in _stats.values()),
                'total_failures':sum(v['num_failures'] for v in _stats.values())}
        data.update(extra)
        with open(STATUS_PATH,'w',encoding='utf-8') as f: json.dump(data,f)
    except Exception: pass

def _pct(times, p):
    if not times: return 0
    s=sorted(times); idx=max(0,int(math.ceil(len(s)*p/100))-1)
    return round(s[idx],2)

def virtual_user():
    import random
    session = requests.Session()
    end_time = _start_time + DURATION
    while time.time() < end_time and not _stop_event.is_set():
        for api in APIS:
            if time.time() >= end_time or _stop_event.is_set(): break
            name=api['name']; method=api['method'].upper()
            url=api['url']; headers=api.get('headers',{})
            body_type=api.get('body_type','json')
            body=api.get('body',{}); params=api.get('params',{})
            kwargs={'headers':headers,'timeout':15,'allow_redirects':True}
            if method in ('POST','PUT','PATCH'):
                if body_type=='form': kwargs['data']=body
                else: kwargs['json']=body
            else:
                kwargs['params']=params
            t0=time.time(); failed=False
            try:
                resp=session.request(method,url,**kwargs)
                elapsed_ms=(time.time()-t0)*1000
                if resp.status_code>=400: failed=True
            except Exception:
                elapsed_ms=(time.time()-t0)*1000; failed=True
            with _stats_lock:
                s=_stats[name]; s['num_requests']+=1; s['method']=method; s['name']=name
                if failed: s['num_failures']+=1
                else: s['response_times'].append(round(elapsed_ms,2))
        gevent.sleep(random.uniform(WAIT_MIN, WAIT_MAX))
    _active[0]=max(0,_active[0]-1)

def main():
    _write_status('starting')
    pool=gevent.pool.Pool(USERS)
    interval=1.0/max(1,SPAWN_RATE)
    for i in range(USERS):
        if _stop_event.is_set(): break
        pool.spawn(virtual_user); _active[0]=i+1
        _write_status('ramping'); gevent.sleep(interval)
    _write_status('running')
    end_time=_start_time+DURATION
    while time.time()<end_time and not _stop_event.is_set():
        gevent.sleep(0.5); _write_status('running')
    _stop_event.set(); pool.join(timeout=15)

    results=[]; all_times=[]; total_req=0; total_fail=0
    elapsed_total=max(time.time()-_start_time,0.001)
    for name,s in _stats.items():
        rt=s['response_times']; n=s['num_requests']; f=s['num_failures']
        total_req+=n; total_fail+=f; all_times.extend(rt)
        results.append({'name':name,'method':s['method'],'num_requests':n,'num_failures':f,
            'avg_response_time':round(statistics.mean(rt),2) if rt else 0,
            'min_response_time':round(min(rt),2) if rt else 0,
            'max_response_time':round(max(rt),2) if rt else 0,
            'response_times':{'50':_pct(rt,50),'75':_pct(rt,75),'90':_pct(rt,90),'95':_pct(rt,95),'99':_pct(rt,99)},
            'total_rps':round(n/elapsed_total,2)})
    agg={'name':'Aggregated','method':'','num_requests':total_req,'num_failures':total_fail,
        'avg_response_time':round(statistics.mean(all_times),2) if all_times else 0,
        'min_response_time':round(min(all_times),2) if all_times else 0,
        'max_response_time':round(max(all_times),2) if all_times else 0,
        'response_times':{'50':_pct(all_times,50),'75':_pct(all_times,75),'90':_pct(all_times,90),'95':_pct(all_times,95),'99':_pct(all_times,99)},
        'total_rps':round(total_req/elapsed_total,2)}
    results.append(agg)
    with open(RESULT_PATH,'w',encoding='utf-8') as f: json.dump(results,f,ensure_ascii=False)
    _write_status('completed',total_requests=total_req,total_failures=total_fail)

def _sig(sig,frame): _stop_event.set()
signal.signal(signal.SIGTERM,_sig); signal.signal(signal.SIGINT,_sig)

if __name__=='__main__': main()
"""


def _parse_duration(run_time: str) -> int:
    s = run_time.strip().lower()
    if s.endswith('h'): return int(s[:-1]) * 3600
    if s.endswith('m'): return int(s[:-1]) * 60
    if s.endswith('s'): return int(s[:-1])
    try: return int(s)
    except ValueError: return 60


def _build_api_payload(api_configs, variables):
    result = []
    for api in api_configs:
        url = api.url
        for k, v in variables.items():
            url = url.replace(f'{{{{{k}}}}}', str(v))

        def _j(raw, d):
            try: return json.loads(raw or d)
            except Exception: return json.loads(d)

        headers = _j(api.headers, '{}')
        body    = _j(api.body,    '{}')
        params  = _j(api.params,  '{}')

        for k, v in variables.items():
            for d in (headers, body, params):
                for dk in list(d.keys()):
                    if isinstance(d[dk], str):
                        d[dk] = d[dk].replace(f'{{{{{k}}}}}', str(v))

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

    duration = _parse_duration(run_time)
    variables = load_global_vars()
    api_payloads = _build_api_payload(apis, variables)

    work_dir = os.path.join(tempfile.gettempdir(), 'gevent_loadtest')
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
            'apis': api_payloads, 'users': users,
            'spawn_rate': spawn_rate, 'duration': duration,
            'wait_min': 0.05, 'wait_max': 0.3,
        }, f, ensure_ascii=False)

    for p in (status_path, result_path):
        try: os.remove(p)
        except FileNotFoundError: pass

    try:
        log_file = open(log_path, 'w', encoding='utf-8')
        proc = subprocess.Popen(
            [sys.executable, worker_path, config_path, status_path, result_path],
            stdout=log_file, stderr=log_file,
        )
    except Exception as e:
        return {'success': False, 'message': f'啟動失敗: {e}'}

    with _lock:
        _tasks[task_id] = {
            'proc': proc, 'pid': proc.pid,
            'status_path': status_path, 'result_path': result_path,
            'log_path': log_path, 'api_ids': api_ids,
            'users': users, 'run_time': run_time, 'duration': duration,
            'start_time': time.time(),
        }

    logger.info(f'[LoadTest] gevent worker PID={proc.pid} task_id={task_id} '
                f'users={users} duration={duration}s')
    return {
        'success': True, 'pid': proc.pid, 'task_id': task_id,
        'script_path': worker_path,
        'message': f'壓測已啟動（gevent greenlet, PID={proc.pid}）',
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
        status = 'error'

    return {
        'found': True, 'task_id': task_id, 'status': status,
        'pid': info['pid'], 'elapsed': elapsed,
        'users': info['users'], 'run_time': info['run_time'],
        'return_code': retcode,
        'active_users':   live.get('active_users', 0),
        'total_requests': live.get('total_requests', 0),
        'total_failures': live.get('total_failures', 0),
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
        return {'success': False, 'message': '結果文件不存在，壓測可能尚未完成'}

    try:
        with open(result_path, encoding='utf-8') as f:
            stats_list = json.load(f)
    except Exception as e:
        return {'success': False, 'message': f'解析結果失敗: {e}'}

    endpoints = [s for s in stats_list if s.get('name') != 'Aggregated']
    agg       = next((s for s in stats_list if s.get('name') == 'Aggregated'), {})
    total_reqs = agg.get('num_requests', 0)
    total_fail = agg.get('num_failures', 0)

    rt = agg.get('response_times', {})
    stats_summary = {
        'total_requests':    total_reqs,
        'total_failures':    total_fail,
        'fail_rate':         round(total_fail / total_reqs * 100, 2) if total_reqs else 0,
        'avg_response_time': agg.get('avg_response_time', 0),
        'min_response_time': agg.get('min_response_time', 0),
        'max_response_time': agg.get('max_response_time', 0),
        'p50': rt.get('50', 0), 'p75': rt.get('75', 0),
        'p90': rt.get('90', 0), 'p95': rt.get('95', 0), 'p99': rt.get('99', 0),
        'rps': agg.get('total_rps', 0),
        'users': info['users'], 'run_time': info['run_time'],
        'per_endpoint': [
            {
                'name':     s.get('name'), 'method': s.get('method'),
                'requests': s.get('num_requests', 0),
                'failures': s.get('num_failures', 0),
                'avg_ms':   s.get('avg_response_time', 0),
                'min_ms':   s.get('min_response_time', 0),
                'max_ms':   s.get('max_response_time', 0),
                'p50_ms':   s.get('response_times', {}).get('50', 0),
                'p90_ms':   s.get('response_times', {}).get('90', 0),
                'p99_ms':   s.get('response_times', {}).get('99', 0),
                'rps':      s.get('total_rps', 0),
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
        matched = apis_map.get(ep['name'])
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
                f"失敗率 {err_rate:.1f}% | avg={ep['avg_ms']}ms "
                f"p50={ep['p50_ms']}ms p90={ep['p90_ms']}ms p99={ep['p99_ms']}ms | "
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

    lines = [
        '# ═══ gevent 壓測配置預覽 ═══',
        '# 引擎：gevent greenlet（非 threading，非 Locust）',
        '# 安裝依賴：pip install gevent requests',
        '',
        'import gevent.monkey; gevent.monkey.patch_all()',
        'import gevent.pool, requests',
        '',
        f'USERS      = <並發數>',
        f'SPAWN_RATE = <每秒增加用戶數>',
        f'DURATION   = <執行秒數>',
        '',
        '# ── 測試接口 ───────────────────────────',
    ]
    for p in payloads:
        lines.append(f'# [{p["method"]}] {p["url"]}')
        lines.append(f'#   name:      {p["name"]}')
        if p['body']:
            lines.append(f'#   body:      {json.dumps(p["body"], ensure_ascii=False)[:80]}')
        if p['params']:
            lines.append(f'#   params:    {json.dumps(p["params"], ensure_ascii=False)[:80]}')
        lines.append('')

    lines += [
        '# ── 虛擬用戶（每個 greenlet 獨立 session）',
        'def virtual_user():',
        '    session = requests.Session()',
        '    while not stop_event.is_set():',
        '        for api in APIS:',
        '            t0 = time.time()',
        '            resp = session.request(api["method"], api["url"], ...)',
        '            record_stats(resp.status_code, (time.time()-t0)*1000)',
        '            gevent.sleep(random.uniform(0.05, 0.3))',
        '',
        '# Ramp-up：每隔 1/SPAWN_RATE 秒啟動一個 greenlet',
        'pool = gevent.pool.Pool(USERS)',
        'for i in range(USERS):',
        '    pool.spawn(virtual_user)',
        '    gevent.sleep(1 / SPAWN_RATE)',
        'pool.join()',
    ]
    return '\n'.join(lines)


# 兼容舊 import
import subprocess
