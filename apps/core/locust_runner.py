"""
Locust 壓測模塊
- 從 ApiConfig 生成 Locust 腳本
- 後台啟動 Locust 進程
- 收集結果並保存到 TestReport
"""
import json
import os
import re
import subprocess
import tempfile
import time
import threading
import logging

logger = logging.getLogger(__name__)

# 全局進程追蹤
_locust_processes = {}
_locust_lock = threading.Lock()


def generate_locust_script(api_configs: list, variables: dict = None) -> str:
    """根據 ApiConfig 列表生成 Locust 腳本字符串"""
    variables = variables or {}

    tasks_code = []
    for api in api_configs:
        # 替換變量
        url = api.url
        for k, v in variables.items():
            url = url.replace(f'{{{{{k}}}}}', str(v))

        # 解析 headers / body
        try:
            headers = json.loads(api.headers or '{}')
        except Exception:
            headers = {}
        try:
            body = json.loads(api.body or '{}')
        except Exception:
            body = {}
        try:
            params = json.loads(api.params or '{}')
        except Exception:
            params = {}

        # 替換變量
        for k, v in variables.items():
            for d in [headers, body, params]:
                for dk in list(d.keys()):
                    if isinstance(d[dk], str):
                        d[dk] = d[dk].replace(f'{{{{{k}}}}}', str(v))

        safe_name = re.sub(r'[^a-zA-Z0-9_]', '_', api.name)[:40]
        method = api.method.lower()

        # 提取路徑（去掉域名部分用於 locust client）
        path_match = re.match(r'https?://[^/]+(.*)', url)
        path = path_match.group(1) if path_match else url
        if not path:
            path = '/'

        body_type = getattr(api, 'body_type', 'json')
        if method == 'post':
            if body_type == 'json':
                body_arg = f'json={json.dumps(body, ensure_ascii=False)}'
            elif body_type == 'form':
                body_arg = f'data={json.dumps(body, ensure_ascii=False)}'
            else:
                body_arg = f'json={json.dumps(body, ensure_ascii=False)}'
        else:
            body_arg = f'params={json.dumps(params, ensure_ascii=False)}'

        task_code = f'''
    @task
    def {safe_name}(self):
        with self.client.{method}(
            "{path}",
            headers={json.dumps(headers, ensure_ascii=False)},
            {body_arg},
            name="{api.name}",
            catch_response=True
        ) as resp:
            if resp.status_code >= 400:
                resp.failure(f"HTTP {{resp.status_code}}")
            else:
                resp.success()
'''
        tasks_code.append(task_code)

    # 提取 host
    host = 'http://localhost:8080'
    if api_configs:
        url_match = re.match(r'(https?://[^/]+)', api_configs[0].url)
        if url_match:
            host = url_match.group(1)

    script = f'''# Auto-generated Locust script by API Test Platform
from locust import HttpUser, task, between

class ApiUser(HttpUser):
    wait_time = between(0.5, 2)
    host = "{host}"

{''.join(tasks_code)}
'''
    return script


def start_locust(task_id: str, api_ids: list, users: int = 10, spawn_rate: int = 2,
                 run_time: str = '60s', headless: bool = True) -> dict:
    """
    啟動 Locust 壓測進程
    返回 {success, pid, script_path, message}
    """
    from apps.core.models import ApiConfig
    from apps.core.executor import load_global_vars

    apis = list(ApiConfig.objects.filter(id__in=api_ids).order_by('sort_order', 'id'))
    if not apis:
        return {'success': False, 'message': '未找到有效接口'}

    variables = load_global_vars()
    script_content = generate_locust_script(apis, variables)

    # 寫臨時腳本
    script_dir = os.path.join(tempfile.gettempdir(), 'locust_scripts')
    os.makedirs(script_dir, exist_ok=True)
    script_path = os.path.join(script_dir, f'locust_{task_id}.py')
    result_path = os.path.join(script_dir, f'result_{task_id}.json')

    with open(script_path, 'w', encoding='utf-8') as f:
        f.write(script_content)

    cmd = [
        'locust',
        '-f', script_path,
        '--headless' if headless else '--web-port', '8089' if not headless else '',
        '--users', str(users),
        '--spawn-rate', str(spawn_rate),
        '--run-time', run_time,
        '--json',
        '--logfile', os.path.join(script_dir, f'locust_{task_id}.log'),
    ]
    cmd = [c for c in cmd if c]  # remove empty strings

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=open(result_path, 'w'),
            stderr=subprocess.PIPE,
            cwd=script_dir,
        )
        with _locust_lock:
            _locust_processes[task_id] = {
                'pid': proc.pid, 'proc': proc,
                'script_path': script_path, 'result_path': result_path,
                'start_time': time.time(), 'status': 'running',
                'users': users, 'run_time': run_time,
                'api_ids': api_ids,
            }
        logger.info(f'[Locust] 啟動 PID={proc.pid} task_id={task_id}')
        return {'success': True, 'pid': proc.pid, 'task_id': task_id,
                'script_path': script_path, 'message': f'Locust 已啟動 PID={proc.pid}'}
    except FileNotFoundError:
        return {'success': False, 'message': 'locust 未安裝，請執行: pip install locust'}
    except Exception as e:
        return {'success': False, 'message': f'啟動失敗: {str(e)}'}


def get_locust_status(task_id: str) -> dict:
    """查詢壓測任務狀態"""
    with _locust_lock:
        info = _locust_processes.get(task_id)
    if not info:
        return {'found': False, 'message': '任務不存在'}

    proc = info['proc']
    retcode = proc.poll()
    elapsed = round(time.time() - info['start_time'], 1)

    if retcode is None:
        status = 'running'
    elif retcode == 0:
        status = 'completed'
    else:
        status = 'error'

    info['status'] = status
    return {
        'found': True, 'task_id': task_id, 'status': status,
        'pid': info['pid'], 'elapsed': elapsed,
        'users': info['users'], 'run_time': info['run_time'],
        'return_code': retcode,
    }


def stop_locust(task_id: str) -> dict:
    """停止壓測進程"""
    with _locust_lock:
        info = _locust_processes.get(task_id)
    if not info:
        return {'success': False, 'message': '任務不存在'}
    try:
        info['proc'].terminate()
        info['status'] = 'stopped'
        return {'success': True, 'message': f'已停止 PID={info["pid"]}'}
    except Exception as e:
        return {'success': False, 'message': str(e)}


def collect_locust_result(task_id: str, report_name: str = None) -> dict:
    """
    讀取 Locust JSON 結果，保存到 TestReport
    返回 {success, report_id, stats}
    """
    with _locust_lock:
        info = _locust_processes.get(task_id)
    if not info:
        return {'success': False, 'message': '任務不存在'}

    result_path = info['result_path']
    if not os.path.exists(result_path):
        return {'success': False, 'message': '結果文件不存在，可能進程尚未完成'}

    try:
        with open(result_path, encoding='utf-8') as f:
            raw = f.read().strip()
        if not raw:
            return {'success': False, 'message': '結果文件為空'}
        stats_list = json.loads(raw)
    except Exception as e:
        return {'success': False, 'message': f'解析結果失敗: {e}'}

    # 彙總統計
    total_reqs = sum(s.get('num_requests', 0) for s in stats_list if s.get('name') != 'Aggregated')
    total_fail = sum(s.get('num_failures', 0) for s in stats_list if s.get('name') != 'Aggregated')
    agg = next((s for s in stats_list if s.get('name') == 'Aggregated'), {})

    stats_summary = {
        'total_requests': total_reqs,
        'total_failures': total_fail,
        'fail_rate': round(total_fail / total_reqs * 100, 2) if total_reqs else 0,
        'avg_response_time': round(agg.get('avg_response_time', 0), 2),
        'min_response_time': round(agg.get('min_response_time', 0), 2),
        'max_response_time': round(agg.get('max_response_time', 0), 2),
        'p50': round(agg.get('response_times', {}).get('50', 0), 2),
        'p90': round(agg.get('response_times', {}).get('90', 0), 2),
        'p99': round(agg.get('response_times', {}).get('99', 0), 2),
        'rps': round(agg.get('total_rps', 0), 2),
        'users': info['users'],
        'run_time': info['run_time'],
        'per_endpoint': [
            {
                'name': s.get('name'), 'method': s.get('method'),
                'requests': s.get('num_requests', 0),
                'failures': s.get('num_failures', 0),
                'avg_ms': round(s.get('avg_response_time', 0), 2),
                'p90_ms': round(s.get('response_times', {}).get('90', 0), 2),
                'rps': round(s.get('total_rps', 0), 2),
            }
            for s in stats_list if s.get('name') != 'Aggregated'
        ],
    }

    # 保存到 TestReport（壓測報告）
    from apps.core.models import TestReport, TestResult, ApiConfig
    passed = total_reqs - total_fail
    rname  = report_name or f'壓測報告-{task_id}-{time.strftime("%Y%m%d_%H%M%S")}'
    report = TestReport.objects.create(
        name=rname, status='completed',
        total=total_reqs, passed=passed,
        failed=total_fail, error=0,
        duration=float(info['run_time'].rstrip('s')) if info['run_time'].endswith('s') else 0,
    )

    # 每個接口一條 TestResult（記錄壓測數據）
    apis = list(ApiConfig.objects.filter(id__in=info['api_ids']))
    for ep in stats_summary['per_endpoint']:
        matched_api = next((a for a in apis if a.name == ep['name']), None)
        err_rate = ep['failures'] / ep['requests'] * 100 if ep['requests'] else 0
        TestResult.objects.create(
            report=report,
            api=matched_api,
            api_name=ep['name'],
            url=matched_api.url if matched_api else ep['name'],
            method=ep.get('method', 'GET'),
            response_status=200 if err_rate == 0 else 500,
            response_time=ep['avg_ms'],
            status='pass' if err_rate == 0 else 'fail',
            error_message=f"失敗率 {err_rate:.1f}%, p90={ep['p90_ms']}ms, RPS={ep['rps']}",
            request_body=json.dumps(stats_summary, ensure_ascii=False, default=str),
        )

    return {
        'success': True, 'report_id': report.id,
        'stats': stats_summary, 'message': f'壓測報告已保存 (report_id={report.id})',
    }


def get_script_preview(api_ids: list) -> str:
    """預覽生成的 Locust 腳本"""
    from apps.core.models import ApiConfig
    from apps.core.executor import load_global_vars
    apis = list(ApiConfig.objects.filter(id__in=api_ids).order_by('sort_order', 'id'))
    if not apis:
        return '# 未找到接口'
    return generate_locust_script(apis, load_global_vars())
