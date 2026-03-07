"""
壓測模塊 — 使用 locust Python API（gevent 驅動）
支援：
  - 單機模式 (LocalRunner)
  - 本機分散式模式 (MasterRunner + N × 本機 WorkerRunner)
  - 跨機器分散式模式 (MasterRunner + 遠端機器手動啟動 Worker)
安裝：pip install locust
"""
import json, os, sys, subprocess, tempfile, time, threading, socket, logging

logger = logging.getLogger(__name__)

_tasks = {}
_lock  = threading.Lock()


def _parse_duration(s: str) -> int:
    s = s.strip().lower()
    if s.endswith('h'): return int(s[:-1]) * 3600
    if s.endswith('m'): return int(s[:-1]) * 60
    if s.endswith('s'): return int(s[:-1])
    try: return int(s)
    except ValueError: return 60


def _subst_vars(obj, variables):
    if isinstance(obj, dict):  return {k: _subst_vars(v, variables) for k, v in obj.items()}
    if isinstance(obj, list):  return [_subst_vars(i, variables) for i in obj]
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
            try:    return json.loads(raw or default)
            except Exception:
                try:    return json.loads(default)
                except: return {}

        headers = _subst_vars(_j(api.headers, '{}'), variables)
        body    = _subst_vars(_j(api.body,    '{}'), variables)
        params  = _subst_vars(_j(api.params,  '{}'), variables)

        # Cookie 合並到 headers（與 executor 保持一致）
        _cookie_raw = (getattr(api, 'cookie', '') or '').strip()
        for k, v in variables.items():
            _cookie_raw = _cookie_raw.replace(f'{{{{{k}}}}}', str(v))
        if _cookie_raw:
            _existing = headers.get('Cookie', '').strip()
            headers['Cookie'] = (_existing + '; ' + _cookie_raw).strip('; ') if _existing else _cookie_raw

        # request_verify 優先，回退到 ssl_verify 選單
        _req_v = (getattr(api, 'request_verify', '') or '').strip()
        if _req_v:
            if _req_v.lower() in ('false', '0', 'no'):
                _verify = False
            elif _req_v.lower() in ('true', '1', 'yes'):
                _verify = True
            else:
                _verify = _req_v
        else:
            _ssl_mode = getattr(api, 'ssl_verify', 'true') or 'true'
            _ssl_cert = (getattr(api, 'ssl_cert', '') or '').strip()
            if _ssl_mode == 'false':
                _verify = False
            elif _ssl_mode == 'custom' and _ssl_cert:
                _verify = _ssl_cert
            else:
                _verify = True

        # OAuth2 Authorization Code Flow 設定
        _use_oauth2 = bool(getattr(api, 'use_oauth2', False))
        _o2_cfg = {}
        if _use_oauth2:
            _o2_cfg = {
                'base_url':     (getattr(api, 'oauth2_base_url', '') or '').strip(),
                'client_id':    (getattr(api, 'oauth2_client_id', '') or '').strip(),
                'client_secret':(getattr(api, 'oauth2_client_secret', '') or '').strip(),
                'redirect_uri': (getattr(api, 'oauth2_redirect_uri', '') or '').strip(),
                'scope':        (getattr(api, 'oauth2_scope', '') or '').strip(),
                'username':     (getattr(api, 'oauth2_username', '') or '').strip(),
                'password':     (getattr(api, 'oauth2_password', '') or '').strip(),
                'allow_redirects': bool(getattr(api, 'oauth2_allow_redirects', True)),
                'verify':       bool(getattr(api, 'oauth2_verify', False)),
            }
        # ── 加密字段（與 executor 保持一致）──
        _encrypted   = bool(getattr(api, 'encrypted', False))
        _enc_key     = (getattr(api, 'encryption_key', '') or '').strip()
        _enc_algo    = (getattr(api, 'encryption_algorithm', 'AES') or 'AES').strip()
        _wrap_key    = ((getattr(api, 'encryption_wrapper_key', '') or 'encrypted').strip() or 'encrypted')
        _body_enc    = (api.get_body_enc_rules() if hasattr(api, 'get_body_enc_rules') else [])

        result.append({
            'name':       api.name,
            'method':     api.method,
            'url':        url,
            'headers':    headers,
            'body':       body,
            'params':     params,
            'body_type':  getattr(api, 'body_type', 'json') or 'json',
            'verify':     _verify,
            'use_oauth2': _use_oauth2,
            'oauth2':     _o2_cfg,
            # 加密
            'encrypted':          _encrypted,
            'encryption_key':     _enc_key,
            'encryption_algorithm': _enc_algo,
            'encryption_wrapper_key': _wrap_key,
            'body_enc_rules':     _body_enc,
        })
    return result


def _free_port(start=5557, end=6500):
    """找一個本機可用 TCP 端口（給 ZeroMQ 用）"""
    for p in range(start, end):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(('0.0.0.0', p))   # 綁定所有接口，真正確認端口未被佔用
                return p
            except OSError:
                continue
    return start


def _get_local_ip() -> str:
    """獲取本機對外 IP（非 127.0.0.1）"""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(('8.8.8.8', 80))
            return s.getsockname()[0]
    except Exception:
        return '127.0.0.1'


# ══════════════════════════════════════════════════════════════
# 公共 User 腳本生成（Master 和 Worker 共用同一段 user 定義）
# ══════════════════════════════════════════════════════════════
_USER_FACTORY = r"""
import re as _re, os as _os, base64 as _b64, json as _json_enc, copy as _copy

# ── 加密工具（與 executor.py 保持一致，AES-GCM / AES-CBC）──
def _encrypt_aes_gcm(plain_text, key_str):
    try:
        from Crypto.Cipher import AES as _AES
        from Crypto.Random import get_random_bytes
        key = (key_str.encode('utf-8') + b'\x00'*32)[:32]
        iv  = get_random_bytes(12)
        cipher = _AES.new(key, _AES.MODE_GCM, nonce=iv)
        ct, tag = cipher.encrypt_and_digest(
            plain_text.encode('utf-8') if isinstance(plain_text, str) else plain_text)
        return _b64.b64encode(iv + ct + tag).decode('utf-8')
    except Exception as _e:
        print(f'[Locust-Encrypt-GCM] error: {_e}')
        return plain_text

def _encrypt_aes_cbc(plain_text, key_str):
    try:
        from Crypto.Cipher import AES as _AES
        from Crypto.Util.Padding import pad
        key = (key_str.encode('utf-8') + b'\x00'*32)[:32]
        iv  = _os.urandom(16)
        cipher = _AES.new(key, _AES.MODE_CBC, iv)
        ct = cipher.encrypt(pad(
            plain_text.encode('utf-8') if isinstance(plain_text, str) else plain_text,
            _AES.block_size))
        return _b64.b64encode(iv + ct).decode('utf-8')
    except Exception as _e:
        print(f'[Locust-Encrypt-CBC] error: {_e}')
        return plain_text

def _apply_body_encryption(body, body_type, api_cfg):
    # 複製 executor.py 的加密邏輯：字段級 AES-GCM（優先）或全局加密
    enc_key   = (api_cfg.get('encryption_key', '') or '').strip()
    encrypted = api_cfg.get('encrypted', False)
    enc_algo  = (api_cfg.get('encryption_algorithm', 'AES') or 'AES').upper()
    wrap_key  = (api_cfg.get('encryption_wrapper_key', '') or 'encrypted').strip() or 'encrypted'
    rules     = api_cfg.get('body_enc_rules', []) or []

    if not enc_key:
        return body, body_type   # 無密鑰 → 明文發送

    # 字段級加密（優先於全局）
    if rules and isinstance(body, dict):
        body = _copy.deepcopy(body)
        for rule in rules:
            field = rule.get('field', '')
            if field in body:
                val = body[field]
                ssrc = str(val) if not isinstance(val, str) else val
                body[field] = _encrypt_aes_gcm(ssrc, enc_key)
        return body, body_type

    # 全局加密
    if encrypted:
        bs = (_json_enc.dumps(body, ensure_ascii=False)
              if isinstance(body, (dict, list)) else str(body or ''))
        enc_val = (_encrypt_aes_cbc(bs, enc_key)
                   if 'CBC' in enc_algo else _encrypt_aes_gcm(bs, enc_key))
        if body_type in ('text', 'data', 'raw'):
            return enc_val, body_type
        return {wrap_key: enc_val}, 'json'

    return body, body_type

def _do_oauth2_flow(o2cfg, verify=False, timeout=30):
    # OAuth2 auth flow: run once per VU on_start, get Bearer token.
    _os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'
    from requests_oauthlib import OAuth2Session
    import re as _re2

    base_url    = o2cfg['base_url'].rstrip('/')
    client_id   = o2cfg['client_id']
    client_secret = o2cfg['client_secret']
    redirect_uri  = o2cfg['redirect_uri']
    scope_raw     = o2cfg.get('scope', '')
    username      = o2cfg['username']
    password      = o2cfg['password']

    _scope_r = scope_raw.strip()
    if _scope_r.startswith('[') and _scope_r.endswith(']'):
        _scope_r = _scope_r[1:-1]
    scope_list = [t.strip().strip('"').strip("'") for t in _re2.split(r'[,\s]+', _scope_r)
                  if t.strip().strip('"').strip("'")] or None

    # 與 executor._get_oauth2_session 完全對齊用戶腳本
    oauth = OAuth2Session(client_id, redirect_uri=redirect_uri, scope=scope_list)
    oauth.verify = verify

    auth_url, _ = oauth.authorization_url(f'{base_url}/oauth2/authorize')

    # 用同一個 oauth session 完成登錄（對應用戶腳本：oauth.post(login_url, data=login_data)）
    login_data = {'username': username, 'password': password}
    oauth.post(f'{base_url}/login', data=login_data)

    # 請求授權地址（allow_redirects=False 取得 Location callback URL）
    res = oauth.get(auth_url, allow_redirects=False)
    loc = res.headers.get('Location', '') or str(res.url)
    if loc and not loc.startswith(('http://','https://')):
        from urllib.parse import urljoin
        loc = urljoin(base_url.rstrip('/') + '/', loc.lstrip('/'))

    # 換取 token（與 executor._get_oauth2_session 完全對齊）
    oauth.fetch_token(
        token_url=f'{base_url}/oauth2/token',
        authorization_response=loc or o2cfg.get('redirect_uri', ''),
        client_secret=client_secret,
    )
    return 'Bearer ' + oauth.token['access_token']

def _make_user_class(apis):
    host = 'http://localhost'
    if apis:
        m = _re.match(r'(https?://[^/]+)', apis[0]['url'])
        if m: host = m.group(1)

    # 收集需要 OAuth2 的唯一配置（按 base_url 去重）
    _oauth2_configs = {}
    for a in apis:
        if a.get('use_oauth2') and a.get('oauth2', {}).get('base_url'):
            key = a['oauth2']['base_url']
            _oauth2_configs[key] = a['oauth2']

    def _make_task(api):
        name      = api['name']
        method    = api['method'].upper()
        path_m    = _re.match(r'https?://[^/]+(.*)', api['url'])
        path      = (path_m.group(1) if path_m else api['url']) or '/'
        headers   = api.get('headers', {})
        body_type = api.get('body_type', 'json')
        body      = api.get('body', {})
        params    = api.get('params', {})
        use_oauth2 = api.get('use_oauth2', False)
        o2_base   = api.get('oauth2', {}).get('base_url', '')
        api_dict  = api   # capture full api dict for verify etc.

        def _task(self):
            # 注入 OAuth2 Bearer token（token 在 on_start 已獲取）
            req_headers = dict(headers)
            if use_oauth2 and o2_base:
                token = getattr(self, '_o2_tokens', {}).get(o2_base, '')
                if token:
                    req_headers['Authorization'] = token

            # 應用加密（字段級 or 全局，與 executor.py 邏輯完全一致）
            _body, _body_type = _apply_body_encryption(body, body_type, api_dict)

            kwargs = {'headers': req_headers, 'name': name, 'catch_response': True,
                      'verify': api_dict.get('verify', True)}
            if method in ('POST', 'PUT', 'PATCH', 'DELETE'):
                if _body_type == 'form':
                    kwargs['data'] = _body
                elif _body_type in ('text', 'text/plain', 'plain'):
                    import json as _json
                    kwargs['data'] = _body if isinstance(_body, str) else _json.dumps(_body)
                    kwargs['headers'] = {**req_headers, 'Content-Type': 'text/plain'}
                else:
                    kwargs['json'] = _body
                if params:
                    kwargs['params'] = params
            else:
                kwargs['params'] = params
            with getattr(self.client, method.lower())(path, **kwargs) as resp:
                resp.failure(f'HTTP {resp.status_code}') if resp.status_code >= 400 else resp.success()

        _task.__name__ = _re.sub(r'\W', '_', name)[:40]
        return _task

    def _on_start(self):
        # OAuth2 auth per VU: run once on_start, store tokens in self._o2_tokens
        self._o2_tokens = {}
        for base_url, o2cfg in _oauth2_configs.items():
            try:
                self._o2_tokens[base_url] = _do_oauth2_flow(
                    o2cfg, verify=o2cfg.get('verify', True)
                )
            except Exception as _e:
                print(f'[OAuth2] 認證失敗 ({base_url}): {_e}')

    methods = {f'task_{i}': task(_make_task(a)) for i, a in enumerate(apis)}
    methods['wait_time'] = between(0.05, 0.3)
    methods['host'] = host
    if _oauth2_configs:
        methods['on_start'] = _on_start
    return type('DynamicUser', (HttpUser,), methods)
"""


# ══════════════════════════════════════════════════════════════
# 單機 Worker 腳本（LocalRunner）
# ══════════════════════════════════════════════════════════════
_SINGLE_WORKER_SCRIPT = _USER_FACTORY + r"""
import sys, json, time
CONFIG_PATH = sys.argv[1]
STATUS_PATH = sys.argv[2]
RESULT_PATH = sys.argv[3]

with open(CONFIG_PATH, encoding='utf-8') as f:
    cfg = json.load(f)

APIS       = cfg['apis']
USERS      = cfg['users']
SPAWN_RATE = cfg['spawn_rate']
DURATION   = cfg['duration']
START_TIME = time.time()

def write_status(status, **kw):
    try:
        d = {'status': status, 'elapsed': round(time.time()-START_TIME, 1), 'mode': 'single'}
        d.update(kw)
        with open(STATUS_PATH, 'w', encoding='utf-8') as f:
            json.dump(d, f)
    except Exception:
        pass

write_status('starting', active_users=0, total_requests=0, total_failures=0)

try:
    from locust import HttpUser, task, between, events
    from locust.env import Environment
    from locust.log import setup_logging
    import gevent
except ImportError as e:
    write_status('error', error=f'缺少依賴: {e}  請執行: pip install locust')
    sys.exit(1)

setup_logging('WARNING', None)
UserClass = _make_user_class(APIS)
env       = Environment(user_classes=[UserClass], events=events)
runner    = env.create_local_runner()

stop_event = gevent.event.Event()

def _updater():
    while not stop_event.is_set():
        s = runner.stats.total
        write_status('running' if runner.user_count > 0 else 'starting',
            active_users=runner.user_count,
            total_requests=s.num_requests,
            total_failures=s.num_failures,
            rps=round(s.current_rps, 1))
        gevent.sleep(1)

gevent.spawn(_updater)
runner.start(user_count=USERS, spawn_rate=SPAWN_RATE)
write_status('ramping', active_users=0, total_requests=0, total_failures=0)

# 支援中途 stop：每秒檢查是否超時
elapsed = 0
while elapsed < DURATION:
    gevent.sleep(1)
    elapsed += 1
    if runner.state in ('stopped', 'stopping'):
        break

runner.stop()
stop_event.set()

def _pct(e, p):
    try:    return round(e.get_response_time_percentile(p/100), 2)
    except: return 0

all_stats = []
for name, entry in runner.stats.entries.items():
    ep_name, ep_method = name
    all_stats.append({'name':ep_name,'method':ep_method,
        'num_requests':entry.num_requests,'num_failures':entry.num_failures,
        'avg_response_time':round(entry.avg_response_time,2),
        'min_response_time':round(entry.min_response_time or 0,2),
        'max_response_time':round(entry.max_response_time or 0,2),
        'response_times':{'50':_pct(entry,50),'75':_pct(entry,75),
            '90':_pct(entry,90),'95':_pct(entry,95),'99':_pct(entry,99)},
        'total_rps':round(entry.total_rps,2)})

total = runner.stats.total
all_stats.append({'name':'Aggregated','method':'',
    'num_requests':total.num_requests,'num_failures':total.num_failures,
    'avg_response_time':round(total.avg_response_time,2),
    'min_response_time':round(total.min_response_time or 0,2),
    'max_response_time':round(total.max_response_time or 0,2),
    'response_times':{'50':_pct(total,50),'75':_pct(total,75),
        '90':_pct(total,90),'95':_pct(total,95),'99':_pct(total,99)},
    'total_rps':round(total.total_rps,2)})

with open(RESULT_PATH,'w',encoding='utf-8') as f:
    json.dump(all_stats, f, ensure_ascii=False)
write_status('completed', active_users=0,
    total_requests=total.num_requests, total_failures=total.num_failures,
    elapsed=round(time.time()-START_TIME,1))
try: env.runner.quit()
except Exception: pass
"""


# ══════════════════════════════════════════════════════════════
# 分散式 Master 腳本（MasterRunner）
# ══════════════════════════════════════════════════════════════
_DIST_MASTER_SCRIPT = _USER_FACTORY + r"""
import sys, json, time
CONFIG_PATH     = sys.argv[1]
STATUS_PATH     = sys.argv[2]
RESULT_PATH     = sys.argv[3]
MASTER_PORT     = int(sys.argv[4])
EXPECT_WORKERS  = int(sys.argv[5])
WAIT_TIMEOUT    = int(sys.argv[6]) if len(sys.argv) > 6 else 120  # 可配置等待逾時

with open(CONFIG_PATH, encoding='utf-8') as f:
    cfg = json.load(f)

APIS       = cfg['apis']
USERS      = cfg['users']
SPAWN_RATE = cfg['spawn_rate']
DURATION   = cfg['duration']
START_TIME = time.time()

def write_status(status, **kw):
    try:
        d = {'status':status,'elapsed':round(time.time()-START_TIME,1),
             'mode':'distributed','master_port':MASTER_PORT}
        d.update(kw)
        with open(STATUS_PATH,'w',encoding='utf-8') as f:
            json.dump(d,f)
    except Exception:
        pass

write_status('waiting_workers', worker_count=0, expect_workers=EXPECT_WORKERS,
             active_users=0, total_requests=0, total_failures=0)

try:
    from locust import HttpUser, task, between, events
    from locust.env import Environment
    from locust.log import setup_logging
    import gevent
except ImportError as e:
    write_status('error', error=f'缺少依賴: {e}  請執行: pip install locust')
    sys.exit(1)

setup_logging('WARNING', None)
UserClass = _make_user_class(APIS)
env       = Environment(user_classes=[UserClass], events=events)
runner    = env.create_master_runner(master_bind_host='*', master_bind_port=MASTER_PORT)

# 等待 Worker 連線（可配置逾時）
wait_start = time.time()
while runner.worker_count < EXPECT_WORKERS:
    if time.time() - wait_start > WAIT_TIMEOUT:
        write_status('error',
            error=f'等待 Worker 逾時 {WAIT_TIMEOUT}s，'
                  f'只連上 {runner.worker_count}/{EXPECT_WORKERS} 個。'
                  f'請確認遠端機器已執行 Worker 命令，且防火牆開放端口 {MASTER_PORT}。')
        sys.exit(1)
    write_status('waiting_workers', worker_count=runner.worker_count,
        expect_workers=EXPECT_WORKERS, active_users=0, total_requests=0, total_failures=0)
    gevent.sleep(1)

runner.start(user_count=USERS, spawn_rate=SPAWN_RATE)
write_status('ramping', worker_count=runner.worker_count,
    expect_workers=EXPECT_WORKERS, active_users=0, total_requests=0, total_failures=0)

stop_event = gevent.event.Event()

def _updater():
    while not stop_event.is_set():
        s  = runner.stats.total
        workers_info = []
        try:
            for wid, w in runner.clients.items():
                workers_info.append({
                    'id':         str(wid)[:16],
                    'user_count': getattr(w,'user_count',0),
                    'state':      getattr(w,'state','unknown'),
                })
        except Exception:
            pass
        write_status('running' if runner.user_count>0 else 'ramping',
            worker_count=runner.worker_count, expect_workers=EXPECT_WORKERS,
            active_users=runner.user_count,
            total_requests=s.num_requests, total_failures=s.num_failures,
            rps=round(s.current_rps,1), workers=workers_info)
        gevent.sleep(1)

gevent.spawn(_updater)

# 支援中途 stop：每秒檢查
elapsed = 0
while elapsed < DURATION:
    gevent.sleep(1)
    elapsed += 1
    if runner.state in ('stopped', 'stopping'):
        break

runner.stop()
stop_event.set()
gevent.sleep(2)  # 等待 worker 最後數據回傳

def _pct(e, p):
    try:    return round(e.get_response_time_percentile(p/100), 2)
    except: return 0

all_stats = []
for name, entry in runner.stats.entries.items():
    ep_name, ep_method = name
    all_stats.append({'name':ep_name,'method':ep_method,
        'num_requests':entry.num_requests,'num_failures':entry.num_failures,
        'avg_response_time':round(entry.avg_response_time,2),
        'min_response_time':round(entry.min_response_time or 0,2),
        'max_response_time':round(entry.max_response_time or 0,2),
        'response_times':{'50':_pct(entry,50),'75':_pct(entry,75),
            '90':_pct(entry,90),'95':_pct(entry,95),'99':_pct(entry,99)},
        'total_rps':round(entry.total_rps,2)})

total = runner.stats.total
all_stats.append({'name':'Aggregated','method':'',
    'num_requests':total.num_requests,'num_failures':total.num_failures,
    'avg_response_time':round(total.avg_response_time,2),
    'min_response_time':round(total.min_response_time or 0,2),
    'max_response_time':round(total.max_response_time or 0,2),
    'response_times':{'50':_pct(total,50),'75':_pct(total,75),
        '90':_pct(total,90),'95':_pct(total,95),'99':_pct(total,99)},
    'total_rps':round(total.total_rps,2),
    'worker_count':runner.worker_count})

with open(RESULT_PATH,'w',encoding='utf-8') as f:
    json.dump(all_stats, f, ensure_ascii=False)
write_status('completed', active_users=0,
    total_requests=total.num_requests, total_failures=total.num_failures,
    worker_count=runner.worker_count, expect_workers=EXPECT_WORKERS,
    elapsed=round(time.time()-START_TIME,1))
try: env.runner.quit()
except Exception: pass
"""


# ══════════════════════════════════════════════════════════════
# 本機 Worker 腳本（WorkerRunner，從本地配置文件讀取）
# ══════════════════════════════════════════════════════════════
_DIST_LOCAL_WORKER_SCRIPT = _USER_FACTORY + r"""
import sys, json
CONFIG_PATH = sys.argv[1]
MASTER_HOST = sys.argv[2]
MASTER_PORT = int(sys.argv[3])
WORKER_ID   = sys.argv[4]

with open(CONFIG_PATH, encoding='utf-8') as f:
    cfg = json.load(f)

APIS = cfg['apis']

try:
    from locust import HttpUser, task, between, events
    from locust.env import Environment
    from locust.log import setup_logging
    import gevent
except ImportError as e:
    print(f'[Worker-{WORKER_ID}] 缺少依賴: {e}', file=sys.stderr)
    sys.exit(1)

setup_logging('WARNING', None)
UserClass = _make_user_class(APIS)
env       = Environment(user_classes=[UserClass], events=events)
runner    = env.create_worker_runner(master_host=MASTER_HOST, master_port=MASTER_PORT)
print(f'[Worker-{WORKER_ID}] 已連線 Master {MASTER_HOST}:{MASTER_PORT}')
runner.greenlet.join()
print(f'[Worker-{WORKER_ID}] 完成退出')
"""


# ══════════════════════════════════════════════════════════════
# 遠端 Worker 引導腳本（HTTP 下載配置，無需共享文件系統）
# Fix: 遠端機器無法訪問 Master 的本地文件，需從 HTTP 取得配置
# ══════════════════════════════════════════════════════════════
_REMOTE_WORKER_SCRIPT_TEMPLATE = _USER_FACTORY + r"""
import sys, json
try:
    import urllib.request as _req
    CONFIG_URL  = sys.argv[1]   # http://MASTER_IP:8000/api/locust/config/TASK_ID/
    MASTER_HOST = sys.argv[2]
    MASTER_PORT = int(sys.argv[3])
    WORKER_ID   = sys.argv[4] if len(sys.argv) > 4 else 'remote'

    print(f'[Worker-{WORKER_ID}] 正在從 {CONFIG_URL} 下載壓測配置...')
    with _req.urlopen(CONFIG_URL, timeout=15) as resp:
        cfg = json.loads(resp.read().decode('utf-8'))
    print(f'[Worker-{WORKER_ID}] 配置下載完成，共 {len(cfg["apis"])} 個接口')
except Exception as e:
    print(f'[ERROR] 下載配置失敗: {e}')
    print(f'[INFO]  請確認 Master 服務可訪問：{sys.argv[1] if len(sys.argv)>1 else "?"}')
    sys.exit(1)

APIS = cfg['apis']

try:
    from locust import HttpUser, task, between, events
    from locust.env import Environment
    from locust.log import setup_logging
    import gevent
except ImportError as e:
    print(f'[Worker-{WORKER_ID}] 缺少依賴: {e}')
    print('[INFO] 請安裝 locust: pip install locust')
    sys.exit(1)

setup_logging('WARNING', None)
UserClass = _make_user_class(APIS)
env       = Environment(user_classes=[UserClass], events=events)
runner    = env.create_worker_runner(master_host=MASTER_HOST, master_port=MASTER_PORT)
print(f'[Worker-{WORKER_ID}] 已連線 Master {MASTER_HOST}:{MASTER_PORT}')
runner.greenlet.join()
print(f'[Worker-{WORKER_ID}] 完成退出')
"""


# ══════════════════════════════════════════════════════════════
# Django 側公開接口
# ══════════════════════════════════════════════════════════════

def start_locust(task_id: str, api_ids: list,
                 users: int = 10, spawn_rate: int = 2,
                 run_time: str = '60s',
                 mode: str = 'single',
                 worker_count: int = 2,
                 remote_workers: list = None,
                 master_bind_ip: str = '',
                 wait_timeout: int = 120) -> dict:
    """
    啟動壓測任務。

    mode:
      'single'      — 單機 LocalRunner
      'distributed' — 本機多進程（1 Master + N 本機 Worker）
      'remote'      — 跨機器（1 Master + 遠端手動/SSH Worker）

    remote_workers: list of str (IP 地址列表), 僅 mode='remote' 時有效
    master_bind_ip: Master 對遠端 Worker 暴露的 IP，默認自動偵測
    wait_timeout:   等待 Worker 連線的最長秒數（默認 120s）
    """
    from apps.core.models import ApiConfig
    from apps.core.executor import load_global_vars

    apis = list(ApiConfig.objects.filter(id__in=api_ids).order_by('sort_order', 'id'))
    if not apis:
        return {'success': False, 'message': '未找到有效接口'}

    # remote 模式：worker_count = 遠端 IP 數量
    if mode == 'remote':
        remote_workers = remote_workers or []
        if not remote_workers:
            return {'success': False, 'message': '跨機器模式需提供至少一個遠端 Worker IP'}
        worker_count = len(remote_workers)

    duration     = _parse_duration(run_time)
    variables    = load_global_vars()
    api_payloads = _build_api_payload(apis, variables)

    work_dir = os.path.join(tempfile.gettempdir(), 'locust_presstest')
    os.makedirs(work_dir, exist_ok=True)

    config_path = os.path.join(work_dir, f'config_{task_id}.json')
    status_path = os.path.join(work_dir, f'status_{task_id}.json')
    result_path = os.path.join(work_dir, f'result_{task_id}.json')

    with open(config_path, 'w', encoding='utf-8') as f:
        json.dump({'apis': api_payloads, 'users': users,
                   'spawn_rate': spawn_rate, 'duration': duration}, f, ensure_ascii=False)

    for p in (status_path, result_path):
        try: os.remove(p)
        except FileNotFoundError: pass

    procs      = []
    log_files  = []   # ← FIX: 保存文件句柄以便後續關閉

    if mode in ('distributed', 'remote'):
        master_port = _free_port()
        actual_master_ip = master_bind_ip.strip() or _get_local_ip()

        master_script = os.path.join(work_dir, f'master_{task_id}.py')
        with open(master_script, 'w', encoding='utf-8') as f:
            f.write(_DIST_MASTER_SCRIPT)

        master_log_path = os.path.join(work_dir, f'master_{task_id}.log')
        master_log_fh   = open(master_log_path, 'w', encoding='utf-8')  # ← FIX: 保存句柄
        log_files.append(master_log_fh)

        try:
            master_proc = subprocess.Popen(
                [sys.executable, master_script,
                 config_path, status_path, result_path,
                 str(master_port), str(worker_count), str(wait_timeout)],
                stdout=master_log_fh,
                stderr=subprocess.STDOUT,
            )
            procs.append(('master', master_proc))
        except Exception as e:
            master_log_fh.close()
            return {'success': False, 'message': f'啟動 Master 失敗: {e}'}

        time.sleep(0.8)  # 等 ZeroMQ socket 就緒

        if mode == 'distributed':
            # 本機多進程 Worker
            local_worker_script = os.path.join(work_dir, f'dworker_{task_id}.py')
            with open(local_worker_script, 'w', encoding='utf-8') as f:
                f.write(_DIST_LOCAL_WORKER_SCRIPT)

            for i in range(worker_count):
                wlog_path = os.path.join(work_dir, f'worker_{task_id}_{i}.log')
                wlog_fh   = open(wlog_path, 'w', encoding='utf-8')  # ← FIX: 保存句柄
                log_files.append(wlog_fh)
                try:
                    wp = subprocess.Popen(
                        [sys.executable, local_worker_script,
                         config_path, '127.0.0.1', str(master_port), str(i)],
                        stdout=wlog_fh,
                        stderr=subprocess.STDOUT,
                    )
                    procs.append((f'worker_{i}', wp))
                except Exception as e:
                    for _, p in procs:
                        try: p.terminate()
                        except: pass
                    for fh in log_files:
                        try: fh.close()
                        except: pass
                    return {'success': False, 'message': f'啟動本機 Worker {i} 失敗: {e}'}

            extra_info = {
                'mode': 'distributed',
                'master_port': master_port,
                'master_ip': actual_master_ip,
                'worker_count': worker_count,
                'worker_pids': [p.pid for n, p in procs if n.startswith('worker')],
            }
            msg = (f'本機分散式壓測已啟動 | Master PID={master_proc.pid} '
                   f'端口={master_port} | {worker_count} 個本機 Worker')

        else:
            # mode == 'remote'：遠端 Worker 需手動啟動（不在本機啟動子進程）
            from django.conf import settings
            django_port = getattr(settings, 'LOCUST_MASTER_DJANGO_PORT', 8000)

            # 為每個遠端 IP 生成啟動命令
            remote_cmds = []
            for i, remote_ip in enumerate(remote_workers):
                config_url = (f'http://{actual_master_ip}:{django_port}'
                              f'/api/locust/remote-config/{task_id}/')
                cmd = (f'python worker.py '
                       f'{config_url} {actual_master_ip} {master_port} remote_{i}')
                remote_cmds.append({
                    'worker_index': i,
                    'remote_ip':    remote_ip,
                    'master_ip':    actual_master_ip,
                    'master_port':  master_port,
                    'config_url':   config_url,
                    'command':      cmd,
                    'pip_cmd':      'pip install locust',
                })

            extra_info = {
                'mode':          'remote',
                'master_port':   master_port,
                'master_ip':     actual_master_ip,
                'django_port':   django_port,
                'worker_count':  worker_count,
                'remote_workers': remote_workers,
                'remote_cmds':   remote_cmds,
                'worker_script_url': (
                    f'http://{actual_master_ip}:{django_port}'
                    f'/api/locust/worker-script/{task_id}/'
                ),
            }
            msg = (f'跨機器分散式壓測已啟動 | Master {actual_master_ip}:{master_port} '
                   f'| 等待 {worker_count} 個遠端 Worker 連線')

        main_proc = master_proc

    else:
        # 單機模式
        single_script = os.path.join(work_dir, f'single_{task_id}.py')
        with open(single_script, 'w', encoding='utf-8') as f:
            f.write(_SINGLE_WORKER_SCRIPT)

        slog_path = os.path.join(work_dir, f'single_{task_id}.log')
        slog_fh   = open(slog_path, 'w', encoding='utf-8')  # ← FIX: 保存句柄
        log_files.append(slog_fh)

        try:
            proc = subprocess.Popen(
                [sys.executable, single_script,
                 config_path, status_path, result_path],
                stdout=slog_fh,
                stderr=subprocess.STDOUT,
            )
            procs.append(('single', proc))
        except Exception as e:
            slog_fh.close()
            return {'success': False, 'message': f'啟動子進程失敗: {e}'}

        main_proc  = proc
        extra_info = {'mode': 'single'}
        msg        = f'壓測已啟動（單機模式，PID={proc.pid}）'

    with _lock:
        _tasks[task_id] = {
            'procs':      procs,
            'main_proc':  main_proc,
            'log_files':  log_files,   # ← FIX: 保存文件句柄
            'pid':        main_proc.pid,
            'status_path': status_path,
            'result_path': result_path,
            'config_path': config_path,
            'api_ids':    api_ids,
            'users':      users,
            'run_time':   run_time,
            'duration':   duration,
            'start_time': time.time(),
            **extra_info,
        }

    logger.info(f'[LoadTest] {msg}  task={task_id}')
    return {
        'success':  True,
        'pid':      main_proc.pid,
        'task_id':  task_id,
        'mode':     mode,
        'message':  msg,
        **extra_info,
    }


def get_locust_status(task_id: str) -> dict:
    with _lock:
        info = _tasks.get(task_id)
    if not info:
        return {'found': False, 'message': '任務不存在'}

    retcode = info['main_proc'].poll()
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
        try:
            lines = []
            for lp in info.get('log_files', []):
                try:
                    lp_name = getattr(lp, 'name', str(lp))
                    with open(lp_name, encoding='utf-8', errors='ignore') as f:
                        lines += f.readlines()[-5:]
                except Exception:
                    pass
            live['error'] = ''.join(lines[-10:]).strip()
        except Exception:
            pass

    result = {
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
        'rps':            live.get('rps', 0),
        'error':          live.get('error', ''),
        'mode':           info.get('mode', 'single'),
    }

    mode = info.get('mode', 'single')
    if mode in ('distributed', 'remote'):
        result.update({
            'worker_count':   live.get('worker_count', 0),
            'expect_workers': info.get('worker_count', 0),
            'master_port':    info.get('master_port', 0),
            'master_ip':      info.get('master_ip', ''),
            'django_port':    info.get('django_port', 8000),
            'workers':        live.get('workers', []),
        })
    if mode == 'remote':
        result['remote_cmds'] = info.get('remote_cmds', [])

    return result


def stop_locust(task_id: str) -> dict:
    with _lock:
        info = _tasks.get(task_id)
    if not info:
        return {'success': False, 'message': '任務不存在'}

    killed = []
    for name, proc in info.get('procs', []):
        try:
            if proc.poll() is None:
                proc.terminate()
                killed.append(f'{name}(PID={proc.pid})')
        except Exception:
            pass

    # 等待進程退出，防止殭屍進程
    for name, proc in info.get('procs', []):
        try:
            proc.wait(timeout=5)
        except Exception:
            pass

    # FIX: 關閉所有日誌文件句柄
    for fh in info.get('log_files', []):
        try:
            fh.close()
        except Exception:
            pass

    # ── FIX: 中途停止時若結果文件不存在，從 status 寫入部分結果 ──
    _result_path = info.get('result_path', '')
    _status_path = info.get('status_path', '')
    time.sleep(0.3)   # 給子進程最後寫盤的機會
    if _result_path and not os.path.exists(_result_path):
        try:
            _st = {}
            if _status_path and os.path.exists(_status_path):
                with open(_status_path, encoding='utf-8') as _sf:
                    _st = json.load(_sf)
            _partial = [{
                'name': 'Aggregated', 'method': '',
                'num_requests':  _st.get('total_requests', 0),
                'num_failures':  _st.get('total_failures', 0),
                'avg_response_time': 0, 'min_response_time': 0, 'max_response_time': 0,
                'response_times': {'50': 0, '75': 0, '90': 0, '95': 0, '99': 0},
                'total_rps': _st.get('rps', 0),
                '_partial': True,
            }]
            with open(_result_path, 'w', encoding='utf-8') as _rf:
                import json as _json2
                _json2.dump(_partial, _rf, ensure_ascii=False)
        except Exception:
            pass

    return {'success': True, 'message': f'已停止：{", ".join(killed) or "無活躍進程"}'}


def get_worker_script(task_id: str) -> str:
    """
    生成遠端 Worker 引導腳本（HTTP 下載配置版本）
    遠端機器下載此腳本後，執行：
        python worker.py <CONFIG_URL> <MASTER_IP> <MASTER_PORT> <WORKER_ID>
    """
    return _REMOTE_WORKER_SCRIPT_TEMPLATE


def get_remote_config(task_id: str) -> dict:
    """
    提供給遠端 Worker 下載的配置 JSON（包含接口信息）
    通過 HTTP 端點暴露，解決遠端機器無法訪問本地文件的問題
    """
    with _lock:
        info = _tasks.get(task_id)
    if not info:
        return None

    config_path = info.get('config_path', '')
    if not config_path or not os.path.exists(config_path):
        return None

    try:
        with open(config_path, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def collect_locust_result(task_id: str, report_name: str = None) -> dict:
    with _lock:
        info = _tasks.get(task_id)
    if not info:
        return {'success': False, 'message': '任務不存在'}

    result_path = info['result_path']
    if not os.path.exists(result_path):
        log_tail = ''
        try:
            lines = []
            for fh in info.get('log_files', []):
                try:
                    lp_name = getattr(fh, 'name', '')
                    if lp_name and os.path.exists(lp_name):
                        with open(lp_name, encoding='utf-8', errors='ignore') as f:
                            lines += f.readlines()[-5:]
                except Exception:
                    pass
            log_tail = ''.join(lines[-8:]).strip()
        except Exception:
            pass
        return {'success': False,
                'message': '結果文件不存在' + (f'\n{log_tail}' if log_tail else '')}

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
    mode         = info.get('mode', 'single')
    worker_count = info.get('worker_count', 1) if mode in ('distributed', 'remote') else 1

    stats_summary = {
        'total_requests':    total_reqs,
        'total_failures':    total_fail,
        'fail_rate':         round(total_fail / total_reqs * 100, 2) if total_reqs else 0,
        'avg_response_time': agg.get('avg_response_time', 0),
        'min_response_time': agg.get('min_response_time', 0),
        'max_response_time': agg.get('max_response_time', 0),
        'p50': rt.get('50', 0), 'p75': rt.get('75', 0),
        'p90': rt.get('90', 0), 'p95': rt.get('95', 0), 'p99': rt.get('99', 0),
        'rps':          agg.get('total_rps', 0),
        'users':        info['users'],
        'run_time':     info['run_time'],
        'mode':         mode,
        'worker_count': worker_count,
        'per_endpoint': [{
            'name':    s.get('name'),    'method':  s.get('method'),
            'requests':  s.get('num_requests', 0),
            'failures':  s.get('num_failures', 0),
            'avg_ms':    s.get('avg_response_time', 0),
            'min_ms':    s.get('min_response_time', 0),
            'max_ms':    s.get('max_response_time', 0),
            'p50_ms':    s.get('response_times', {}).get('50', 0),
            'p90_ms':    s.get('response_times', {}).get('90', 0),
            'p99_ms':    s.get('response_times', {}).get('99', 0),
            'rps':       s.get('total_rps', 0),
        } for s in endpoints],
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
            error_message=(f"失敗率 {err_rate:.1f}% | avg={ep['avg_ms']}ms "
                           f"p50={ep['p50_ms']}ms p90={ep['p90_ms']}ms "
                           f"p99={ep['p99_ms']}ms | RPS={ep['rps']}"),
            request_body=json.dumps(stats_summary, ensure_ascii=False, default=str),
        )

    return {'success': True, 'report_id': report.id, 'stats': stats_summary,
            'message': f'壓測報告已保存 (report_id={report.id})'}


def get_script_preview(api_ids: list) -> str:
    from apps.core.models import ApiConfig
    from apps.core.executor import load_global_vars
    import re

    apis = list(ApiConfig.objects.filter(id__in=api_ids).order_by('sort_order', 'id'))
    if not apis: return '# 未找到接口'

    variables = load_global_vars()
    payloads  = _build_api_payload(apis, variables)

    host = 'http://localhost'
    if apis:
        m = re.match(r'(https?://[^/]+)', apis[0].url)
        if m: host = m.group(1)

    # 收集 OAuth2 配置（去重）
    oauth2_configs = {}
    for p in payloads:
        if p.get('use_oauth2') and p.get('oauth2', {}).get('base_url'):
            oauth2_configs[p['oauth2']['base_url']] = p['oauth2']

    # on_start 方法（若有 OAuth2）
    on_start_code = ''
    if oauth2_configs:
        cfg_repr = json.dumps(oauth2_configs, ensure_ascii=False, indent=8)
        on_start_code = (
            '    # OAuth2 Token 緩存（每個 VU 啟動時認證一次）\n'
            '    _OAUTH2_CONFIGS = ' + cfg_repr + '\n\n'
            '    def on_start(self):\n'
            '        import os, re as _re\n'
            '        from requests_oauthlib import OAuth2Session\n'
            '        os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")\n'
            '        self._o2_tokens = {}\n'
            '        for base_url, cfg in self._OAUTH2_CONFIGS.items():\n'
            '            try:\n'
            '                scope_list = [s.strip() for s in _re.split(r"[,\\s]+", cfg.get("scope","").strip()) if s.strip()] or None\n'
            '                oauth = OAuth2Session(cfg["client_id"], redirect_uri=cfg["redirect_uri"], scope=scope_list)\n'
            '                oauth.verify = False\n'
            '                auth_url, state = oauth.authorization_url(f\"{base_url}/oauth2/authorize\")\n'
            '                oauth.post(f\"{base_url}/login\", data={"username": cfg["username"], "password": cfg["password"]}, allow_redirects=True, timeout=30)\n'
            '                res = oauth.get(auth_url, allow_redirects=False, timeout=30)\n'
            '                loc = res.headers.get("Location", "") or str(res.url)\n'
            '                if loc and not loc.startswith(("http://","https://")):\n'
            '                    from urllib.parse import urljoin\n'
            '                    loc = urljoin(base_url + "/", loc.lstrip("/"))\n'
            '                oauth.fetch_token(token_url=f\"{base_url}/oauth2/token\", authorization_response=loc or cfg["redirect_uri"], client_secret=cfg["client_secret"], verify=False, timeout=30)\n'
            '                self._o2_tokens[base_url] = "Bearer " + oauth.token["access_token"]\n'
            '            except Exception as e:\n'
            '                print(f"[OAuth2] {base_url} 認證失敗: {e}")\n\n'
        )

    task_methods = []
    for i, p in enumerate(payloads):
        path_m = re.match(r'https?://[^/]+(.*)', p['url'])
        path   = (path_m.group(1) if path_m else p['url']) or '/'
        method = p['method'].lower()
        body_arg = (f"data={json.dumps(p['body'],ensure_ascii=False)}"
                    if p['body_type'] == 'form' and method in ('post', 'put', 'patch', 'delete')
                    else f"json={json.dumps(p['body'],ensure_ascii=False)}"
                    if method in ('post', 'put', 'patch', 'delete')
                    else f"params={json.dumps(p['params'],ensure_ascii=False)}")
        # OAuth2 header 注入
        hdr_code = json.dumps(p['headers'], ensure_ascii=False)
        if p.get('use_oauth2') and p.get('oauth2', {}).get('base_url'):
            b64url = p['oauth2']['base_url']
            hdr_inject = (
                f'        _hdr = dict({hdr_code})\n'
                f'        _tok = getattr(self, "_o2_tokens", {{}}).get({json.dumps(b64url)}, "")\n'
                f'        if _tok: _hdr["Authorization"] = _tok\n'
            )
            hdr_ref = '_hdr'
        else:
            hdr_inject = ''
            hdr_ref = hdr_code
        task_methods.append(
            f'    @task\n'
            f'    def task_{i}_{re.sub(chr(92)+"W","_",p["name"])[:20]}(self):\n'
            + (f'{hdr_inject}' if hdr_inject else '')
            + f'        with self.client.{method}("{path}", {body_arg},\n'
            f'                headers={hdr_ref},\n'
            f'                name="{p["name"]}", catch_response=True) as resp:\n'
            f'            if resp.status_code >= 400: resp.failure(f"HTTP {{resp.status_code}}")\n'
            f'            else: resp.success()\n'
        )
    return (
        '# ═══ locust 壓測腳本（支援 OAuth2 + 分散式）═══\n'
        '# 單機：locust -f this.py --headless -u 50 -r 5 -t 60s\n'
        '# 分散式 Master：locust -f this.py --master\n'
        '# 分散式 Worker：locust -f this.py --worker --master-host=127.0.0.1\n\n'
        'from locust import HttpUser, task, between\n\n'
        f'class ApiUser(HttpUser):\n'
        f'    host = "{host}"\n'
        f'    wait_time = between(0.05, 0.3)\n\n'
        + on_start_code
        + '\n'.join(task_methods)
    )
