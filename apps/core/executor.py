"""
API 執行引擎 v3
新增：
  - body_type: json / form / raw / files
  - json.dumps 支持（raw 模式）
  - files 上傳
  - requests.Session() 支持
  - 自定義 timeout
  - asyncio + httpx 完善異步（帶 timeout）
  - DeepDiff 斷言（支持忽略字段）
"""
import re
import os
import json
import time
import base64
import hashlib
import asyncio
import logging
import threading

import requests
import httpx

logger = logging.getLogger(__name__)

# ── 運行時狀態 ───────────────────────────────────────
_runtime_vars: dict = {}
_runtime_lock = threading.Lock()
_session_store: dict = {}
_session_lock = threading.Lock()


def reset_runtime_vars():
    global _runtime_vars, _session_store
    with _runtime_lock:
        _runtime_vars = {}
    with _session_lock:
        for s in _session_store.values():
            try: s.close()
            except Exception: pass
        _session_store = {}


def set_runtime_var(name: str, value):
    with _runtime_lock:
        _runtime_vars[name] = value


def get_runtime_vars() -> dict:
    with _runtime_lock:
        return dict(_runtime_vars)


def load_global_vars() -> dict:
    from apps.core.models import GlobalVariable
    db_vars = {v.name: v.value for v in GlobalVariable.objects.all()}
    with _runtime_lock:
        db_vars.update(_runtime_vars)
    return db_vars


def _get_session(api_id: int) -> requests.Session:
    with _session_lock:
        if api_id not in _session_store:
            _session_store[api_id] = requests.Session()
        return _session_store[api_id]


# ── 變量替換 ─────────────────────────────────────────

def _replace_vars(text: str, variables: dict) -> str:
    if not text:
        return text
    def replacer(m):
        return str(variables.get(m.group(1).strip(), m.group(0)))
    return re.sub(r'\{\{([^}]+)\}\}', replacer, text)


def replace_vars_in_dict(data, variables: dict):
    """
    遞歸替換 dict/list/str 中的 {{變量名}}。
    支持 body 為純字符串的情況（text/plain 模式）。
    """
    if isinstance(data, str):
        return _replace_vars(data, variables)
    if not isinstance(data, dict):
        return data
    result = {}
    for k, v in data.items():
        if isinstance(v, str):
            result[k] = _replace_vars(v, variables)
        elif isinstance(v, dict):
            result[k] = replace_vars_in_dict(v, variables)
        elif isinstance(v, list):
            result[k] = [_replace_vars(i, variables) if isinstance(i, str) else i for i in v]
        else:
            result[k] = v
    return result


def replace_vars_in_sql(sql: str, variables: dict) -> str:
    return _replace_vars(sql, variables)


# ── 加密工具 ─────────────────────────────────────────

def encrypt_gcm(ssrc: str, raw: str) -> str:
    """
    AES-GCM 加密，完全符合業務代碼規格：
        iv = bytearray(12)  # 12字節零IV
        cipher = AES.new(raw_1, AES.MODE_GCM, iv)
        ciphertext, tag = cipher.encrypt_and_digest(ssrc)
        encrypted = iv + ciphertext + tag
        return base64.b64encode(encrypted).decode('utf-8')

    raw 密鑰：直接使用原始字節，不補齊（AES-GCM 支持16/24/32字節）
    若長度不在上述範圍，補齊到最近的有效長度。
    """
    from Crypto.Cipher import AES as _AES
    raw_bytes = raw.encode('utf-8')
    # 調整密鑰至16/24/32字節
    for klen in (16, 24, 32):
        if len(raw_bytes) <= klen:
            raw_bytes = raw_bytes.ljust(klen, b'\x00')
            break
    else:
        raw_bytes = raw_bytes[:32]

    iv = bytearray(12)
    cipher = _AES.new(raw_bytes, _AES.MODE_GCM, nonce=iv)
    ciphertext, tag = cipher.encrypt_and_digest(ssrc.encode('utf-8'))
    encrypted = bytes(iv) + ciphertext + tag
    return base64.b64encode(encrypted).decode('utf-8')


def encrypt_body(body: str, algorithm: str, key: str) -> str:
    """對整個 body 字符串加密（全局加密模式）"""
    try:
        if algorithm == 'AES-GCM':
            return encrypt_gcm(body, key)
        elif algorithm == 'BASE64':
            return base64.b64encode(body.encode()).decode()
        elif algorithm == 'MD5':
            return hashlib.md5(body.encode()).hexdigest()
        elif algorithm == 'AES':
            from Crypto.Cipher import AES as _AES
            from Crypto.Util.Padding import pad
            raw_bytes = key.encode('utf-8')
            for klen in (16, 24, 32):
                if len(raw_bytes) <= klen:
                    raw_bytes = raw_bytes.ljust(klen, b'\x00')
                    break
            else:
                raw_bytes = raw_bytes[:32]
            cipher = _AES.new(raw_bytes, _AES.MODE_CBC)
            ct = cipher.encrypt(pad(body.encode('utf-8'), _AES.block_size))
            return json.dumps({
                'iv': base64.b64encode(cipher.iv).decode(),
                'data': base64.b64encode(ct).decode()
            })
    except Exception as e:
        logger.error(f'加密失敗 ({algorithm}): {e}')
    return body


def apply_body_enc_rules(body: dict, rules: list, default_raw: str,
                          variables: dict) -> dict:
    """
    對 body dict 中的指定字段做 AES-GCM 加密，支持 Bodys 模式：

        Bodys = {
            "param": encrypt(json.dumps(payload), raw),
            "url":   encrypt("user/loginAndRegister", raw)
        }

    rules 格式（存在 body_enc_rules 字段）:
      [
        {
          "field":      "param",            # 目標字段名（寫入 body 的 key）
          "ssrc":       "{{payload}}",      # 要加密的值；支持 {{變量名}}；
                                            # 也可以是字面量 "user/loginAndRegister"
          "json_dumps": true,               # true = 先對 ssrc 解析後 json.dumps，再加密
                                            # false/缺省 = 直接加密 ssrc 字符串
          "raw":        "DLMwO2OmfYnEfo7s"  # 可選，覆蓋全局 encryption_key
        },
        {
          "field": "url",
          "ssrc":  "user/loginAndRegister"  # 字面量
        }
      ]

    返回新 body dict（不修改原始對象）。
    """
    if not rules:
        return body

    result = dict(body) if isinstance(body, dict) else {}

    for rule in rules:
        field    = rule.get('field', '').strip()
        ssrc_tpl = rule.get('ssrc', '').strip()
        raw      = rule.get('raw', '').strip() or default_raw
        do_dumps = bool(rule.get('json_dumps', False))

        if not field or not ssrc_tpl:
            logger.warning(f'[BodyEnc] 規則缺少 field 或 ssrc，已跳過: {rule}')
            continue
        if not raw:
            logger.warning(f'[BodyEnc] 字段 {field} 無加密密鑰(raw)，已跳過')
            continue

        # 1. 變量替換
        ssrc_str = _replace_vars(ssrc_tpl, variables)

        # 2. json_dumps 模式：先嘗試解析為 Python 對象再序列化
        if do_dumps:
            # 從運行時變量或當前 body 中取值（如果 ssrc_str 是個引用）
            val_candidate = variables.get(ssrc_str) if ssrc_str in variables else result.get(ssrc_str)
            if val_candidate is not None:
                # 取到實際對象，json.dumps
                ssrc_str = json.dumps(val_candidate, ensure_ascii=False)
            else:
                # ssrc_str 本身可能已是 JSON 字符串，直接使用
                try:
                    # 驗證是合法 JSON
                    json.loads(ssrc_str)
                except (json.JSONDecodeError, TypeError):
                    # 不是 JSON，當作字符串 dumps
                    ssrc_str = json.dumps(ssrc_str, ensure_ascii=False)

        # 3. AES-GCM 加密
        try:
            encrypted_val = encrypt_gcm(ssrc_str, raw)
            result[field] = encrypted_val
            logger.debug(f'[BodyEnc] field={field} ssrc_len={len(ssrc_str)} → encrypted OK')
        except Exception as e:
            logger.error(f'[BodyEnc] field={field} 加密失敗: {e}')

    return result


# ── JSON 路徑提取 ────────────────────────────────────

def extract_value(data, path: str):
    try:
        path = path.lstrip('$').lstrip('.')
        parts = re.split(r'[.\[\]]', path)
        cur = data
        for p in parts:
            if not p:
                continue
            cur = cur[p] if isinstance(cur, dict) else cur[int(p)]
        return cur
    except Exception:
        return None


# ── HTTP 斷言 ────────────────────────────────────────

def run_assertions(assertions: list, response_status: int, response_data) -> list:
    results = []
    for rule in assertions:
        try:
            a_type   = rule.get('type', '')
            expected = rule.get('expected')
            item = {'rule': rule, 'expected': expected, 'actual': None, 'passed': False, 'message': ''}

            if a_type == 'status_code':
                actual = response_status
                item.update({'actual': actual, 'passed': str(actual) == str(expected),
                             'message': f'狀態碼 {actual} {"==" if str(actual)==str(expected) else "!="} {expected}'})
            elif a_type == 'json_path':
                path = rule.get('path', '')
                actual = extract_value(response_data, path)
                item.update({'actual': actual, 'passed': str(actual) == str(expected),
                             'message': f'路徑[{path}]={actual} {"==" if str(actual)==str(expected) else "!="} {expected}'})
            elif a_type == 'contains':
                body_str = json.dumps(response_data, ensure_ascii=False) if isinstance(response_data, (dict, list)) else str(response_data)
                passed = str(expected) in body_str
                item.update({'actual': '(響應體)', 'passed': passed,
                             'message': f'響應體{"包含" if passed else "不包含"} "{expected}"'})
            elif a_type == 'not_empty':
                path = rule.get('path', '')
                actual = extract_value(response_data, path)
                passed = actual is not None and actual != '' and actual != [] and actual != {}
                item.update({'actual': actual, 'passed': passed,
                             'message': f'路徑[{path}] {"非空" if passed else "為空"}'})
            elif a_type == 'regex':
                path = rule.get('path', '')
                actual = extract_value(response_data, path) if path else str(response_data)
                try:
                    passed = bool(re.search(str(expected), str(actual)))
                except Exception:
                    passed = False
                item.update({'actual': actual, 'passed': passed,
                             'message': f'正則[{path}]"{actual}" {"匹配" if passed else "不匹配"} /{expected}/'})

            results.append(item)
        except Exception as e:
            results.append({'rule': rule, 'passed': False, 'message': f'斷言異常: {e}', 'actual': None, 'expected': None})
    return results


# ── DeepDiff 斷言 ─────────────────────────────────────

def run_deepdiff_assertions(rules: list, response_data) -> list:
    results = []
    for rule in rules:
        label         = rule.get('label', 'DeepDiff 斷言')
        expected_raw  = rule.get('expected', {})
        ignore_fields = rule.get('ignore_fields', [])
        check_path    = rule.get('check_path', '')
        item = {'rule': rule, 'passed': False, 'message': '', 'diff': None}

        try:
            expected = json.loads(expected_raw) if isinstance(expected_raw, str) else expected_raw
        except Exception:
            expected = expected_raw

        actual = extract_value(response_data, check_path) if check_path else response_data

        try:
            from deepdiff import DeepDiff
            exclude_paths = {f"root['{f}']" for f in ignore_fields} | {f'root["{f}"]' for f in ignore_fields}
            exclude_regex = [re.compile(rf"root\[.*\]\['{re.escape(f)}'\]") for f in ignore_fields]
            diff = DeepDiff(expected, actual,
                            exclude_paths=exclude_paths,
                            exclude_regex_paths=exclude_regex or None,
                            ignore_order=True, significant_digits=6)
            passed   = len(diff) == 0
            diff_str = str(diff)[:500] if diff else None
            item.update({'passed': passed, 'diff': diff_str,
                         'message': f'[DeepDiff] {label}: {"✓ 一致" if passed else "✗ 差異→" + (diff_str or "")}'})
        except ImportError:
            try:
                passed = json.dumps(actual, sort_keys=True) == json.dumps(expected, sort_keys=True)
            except Exception:
                passed = str(actual) == str(expected)
            item.update({'passed': passed,
                         'message': f'[DeepDiff↓] {label}: {"✓" if passed else "✗"} (deepdiff 未安裝，降級比較)'})
        except Exception as e:
            item.update({'passed': False, 'message': f'[DeepDiff] {label}: 異常 {str(e)}'})

        results.append(item)
    return results


# ── 構建請求 kwargs ──────────────────────────────────

def _build_request_kwargs(method, url, headers, params, body, body_type, timeout):
    """
    構建 requests 請求 kwargs。

    body_type 對所有 HTTP 方法（GET/POST/PUT/PATCH/DELETE）行為一致：
      json   → json=body
      data   → data=body（dict 或任意字符串）
      params → body 合併到 query string（GET/POST 都適用）
      form   → data={k:str(v)}（form-urlencoded）
      text   → data=str，自動加 Content-Type: text/plain
      raw    → data=json.dumps(body)，自動加 Content-Type: application/json
      files  → files=..., data=...

    只有 body 為空（{}、''、None）時才不發送 body。
    """
    kwargs = {
        'url': url,
        'headers': dict(headers or {}),
        'params': {k: v for k, v in (params or {}).items() if k != '_raw' and v not in ('', None)},
        'timeout': timeout,
    }

    # 純字符串 params（如 UUID）：直接追加到 URL
    if isinstance(params, dict) and '_raw' in params:
        raw_val = str(params['_raw']).strip('/')
        sep = '&' if '?' in kwargs['url'] else '?'
        # 如果是純 key=value 字符串，追加到 query；否則追加到路徑後
        if '=' in raw_val:
            kwargs['url'] = kwargs['url'] + sep + raw_val
        else:
            kwargs['url'] = kwargs['url'].rstrip('/') + '/' + raw_val


    # body 為空則不設置任何 body 參數
    body_is_empty = body in ({}, '', None, [])

    if body_type == 'json':
        if not body_is_empty:
            kwargs['json'] = body

    elif body_type == 'data':
        kwargs['data'] = body if isinstance(body, (dict, str)) else str(body or '')

    elif body_type == 'params':
        # body 合併到 query string（適合 GET 傳參，或 POST 額外追加 URL 參數）
        extra = {}
        if isinstance(body, dict):
            extra = {k: str(v) for k, v in body.items() if v not in ('', None)}
        elif isinstance(body, str) and body.strip():
            try:
                extra = {k: str(v) for k, v in json.loads(body).items()}
            except Exception:
                pass
        kwargs['params'] = {**kwargs['params'], **extra}

    elif body_type == 'form':
        if not body_is_empty:
            kwargs['data'] = {k: str(v) for k, v in body.items()} if isinstance(body, dict) else {}

    elif body_type == 'text':
        text_val = body if isinstance(body, str) else (
            json.dumps(body, ensure_ascii=False) if isinstance(body, (dict, list)) else str(body or '')
        )
        if text_val:
            kwargs['data'] = text_val
            if 'Content-Type' not in kwargs['headers']:
                kwargs['headers']['Content-Type'] = 'text/plain; charset=utf-8'

    elif body_type == 'raw':
        if not body_is_empty:
            if isinstance(body, (dict, list)):
                kwargs['data'] = json.dumps(body, ensure_ascii=False)
                if 'Content-Type' not in kwargs['headers']:
                    kwargs['headers']['Content-Type'] = 'application/json'
            else:
                kwargs['data'] = str(body)

    elif body_type == 'files':
        files_list = []
        body_copy = dict(body) if isinstance(body, dict) else {}
        raw_files = body_copy.pop('__files__', [])
        for fi in raw_files:
            fpath = fi.get('path', '')
            if fpath and os.path.isfile(fpath):
                files_list.append((fi.get('field', 'file'),
                                   (os.path.basename(fpath), open(fpath, 'rb'),
                                    fi.get('mime', 'application/octet-stream'))))
        if files_list:
            kwargs['files'] = files_list
        if body_copy:
            kwargs['data'] = {k: str(v) for k, v in body_copy.items()}

    else:
        # 默認按 json 處理
        if not body_is_empty:
            kwargs['json'] = body

    return kwargs


# ── 同步請求（requests / Session）───────────────────

def _do_sync_request(method, url, headers, params, body, body_type, timeout,
                     use_session=False, api_id=None):
    kw = _build_request_kwargs(method, url, headers, params, body, body_type, timeout)
    req_url = kw.pop('url')
    sess = _get_session(api_id) if (use_session and api_id) else requests
    resp = sess.request(method.upper(), req_url, **kw)
    return resp.status_code, dict(resp.headers), resp.text


# ── 異步請求（asyncio + httpx）──────────────────────

async def _do_async_request(method, url, headers, params, body, body_type, timeout):
    timeout_cfg = httpx.Timeout(connect=min(timeout, 10), read=timeout, write=timeout, pool=timeout)
    headers = dict(headers or {})
    params  = {k: v for k, v in (params or {}).items() if v not in ('', None)}

    async with httpx.AsyncClient(timeout=timeout_cfg) as client:
        # 過濾 _raw，並處理純字符串 params
        clean_params = {k: v for k, v in params.items() if k != '_raw' and v not in ('', None)}
        req_url = url
        if '_raw' in params:
            raw_val = str(params['_raw']).strip('/')
            sep = '&' if '?' in req_url else '?'
            req_url = (req_url + sep + raw_val) if '=' in raw_val else (req_url.rstrip('/') + '/' + raw_val)

        kw = {'headers': headers, 'params': clean_params}
        body_is_empty = body in ({}, '', None, [])

        if body_type == 'json':
            if not body_is_empty:
                kw['json'] = body

        elif body_type == 'data':
            kw['data'] = body if isinstance(body, (dict, str)) else str(body or '')

        elif body_type == 'params':
            extra = {}
            if isinstance(body, dict):
                extra = {k: str(v) for k, v in body.items() if v not in ('', None)}
            elif isinstance(body, str) and body.strip():
                try:
                    extra = {k: str(v) for k, v in json.loads(body).items()}
                except Exception:
                    pass
            kw['params'] = {**kw['params'], **extra}

        elif body_type == 'form':
            if not body_is_empty:
                kw['data'] = {k: str(v) for k, v in body.items()} if isinstance(body, dict) else {}

        elif body_type == 'text':
            text_val = body if isinstance(body, str) else (
                json.dumps(body, ensure_ascii=False) if isinstance(body, (dict, list)) else str(body or '')
            )
            if text_val:
                kw['content'] = text_val.encode('utf-8')
                if 'Content-Type' not in headers:
                    kw['headers']['Content-Type'] = 'text/plain; charset=utf-8'

        elif body_type == 'raw':
            if not body_is_empty:
                raw_str = json.dumps(body, ensure_ascii=False) if isinstance(body, (dict, list)) else str(body)
                kw['content'] = raw_str.encode('utf-8')
                if 'Content-Type' not in headers:
                    kw['headers']['Content-Type'] = 'application/json'

        else:
            if not body_is_empty:
                kw['json'] = body

        resp = await client.request(method.upper(), req_url, **kw)
        return resp.status_code, dict(resp.headers), resp.text


def _run_async_coro(coro):
    """安全在同步上下文中執行 asyncio 協程"""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(asyncio.run, coro).result()
        if loop.is_closed():
            raise RuntimeError('closed')
        return loop.run_until_complete(coro)
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()


# ── 核心執行 ─────────────────────────────────────────

def execute_api(api_config, extra_vars: dict = None) -> dict:
    from apps.core.db_utils import execute_sql_statements, run_db_assertions

    variables = load_global_vars()
    if extra_vars:
        variables.update(extra_vars)

    # ── Step 1: 前置 Redis 取值（必須最先執行，讓注入的變量能在 body/params/url 中使用）──
    pre_redis_log = []
    pre_redis_rules = api_config.get_pre_redis_rules() if hasattr(api_config, 'get_pre_redis_rules') else []
    if pre_redis_rules:
        from apps.core.redis_utils import get_client
        from apps.core.models import RedisConfig
        for rule in pre_redis_rules:
            redis_id      = rule.get('redis_id')
            key_tpl       = rule.get('key', '').strip()
            var_name      = rule.get('var_name', '').strip()
            extract_field = rule.get('extract_field', '').strip()
            if not (redis_id and key_tpl and var_name):
                continue
            real_key = _replace_vars(key_tpl, variables)
            entry = {'key': real_key, 'var_name': var_name, 'success': False}
            try:
                cfg = RedisConfig.objects.get(pk=redis_id)
                client, err = get_client(cfg)
                if err:
                    entry['error'] = err
                else:
                    raw = client.get(real_key)
                    client.close()
                    if raw is None:
                        entry['error'] = f'key [{real_key}] 不存在或已過期'
                    else:
                        val = raw
                        if extract_field:
                            try:
                                data_obj = json.loads(raw) if isinstance(raw, str) else raw
                                if isinstance(data_obj, dict) and extract_field in data_obj:
                                    val = str(data_obj[extract_field])
                            except Exception:
                                pass
                        variables[var_name] = str(val)
                        set_runtime_var(var_name, str(val))
                        entry.update({'success': True, 'value': str(val)})
            except Exception as e:
                entry['error'] = str(e)
            pre_redis_log.append(entry)

    # ── Step 2: 變量替換（此時 variables 已包含 Redis 注入的值）──
    url       = _replace_vars(api_config.url, variables)
    headers   = replace_vars_in_dict(api_config.get_headers(), variables)
    params    = replace_vars_in_dict(api_config.get_params(), variables)
    body      = replace_vars_in_dict(api_config.get_body(), variables)
    timeout   = max(int(getattr(api_config, 'timeout', 30) or 30), 1)
    use_async   = bool(getattr(api_config, 'use_async', False))
    use_session = bool(getattr(api_config, 'use_session', False))
    body_type   = getattr(api_config, 'body_type', 'json') or 'json'

    # ── Body 字段級加密（AES-GCM per-field）──
    body_enc_rules = api_config.get_body_enc_rules() if hasattr(api_config, 'get_body_enc_rules') else []
    enc_key        = getattr(api_config, 'encryption_key', '') or ''
    enc_algo       = getattr(api_config, 'encryption_algorithm', 'AES') or 'AES'
    enc_applied    = []
    if body_enc_rules:
        body = apply_body_enc_rules(body, body_enc_rules, enc_key, variables)
        enc_applied = body_enc_rules   # 記錄哪些字段做了加密

    # ── 全局 Body 加密（整體加密模式，body_enc_rules 優先）──
    request_body_raw = body
    encrypted_body   = None
    if getattr(api_config, 'encrypted', False) and enc_key and not body_enc_rules:
        bs = json.dumps(body, ensure_ascii=False) if isinstance(body, (dict, list)) else str(body or '')
        encrypted_body = encrypt_body(bs, enc_algo, enc_key)
        # text / data / raw 模式：加密結果直接作為裸字符串發送
        # 等價: requests.post(url, data=encrypt(payload), headers=headers)
        # 不包裝成 {"encrypted":"..."} — 那樣會讓服務端收到錯誤格式
        if body_type in ('text', 'data', 'raw'):
            body = encrypted_body
            # body_type 保持不變，繼續以原模式（data=/text/raw）發送
        else:
            # json / form 模式：才包裝成 JSON 對象
            body      = {'encrypted': encrypted_body}
            body_type = 'json'

    # 前置 SQL
    pre_sql_result = ''
    if getattr(api_config, 'pre_sql', '') and getattr(api_config, 'pre_sql_db_id', None):
        try:
            res = execute_sql_statements(api_config.pre_sql_db, replace_vars_in_sql(api_config.pre_sql, variables))
            pre_sql_result = json.dumps(res, ensure_ascii=False, default=str)
        except Exception as e:
            pre_sql_result = json.dumps({'success': False, 'error': str(e)})

    # HTTP 請求
    start = time.time()
    error_message = ''
    response_status, response_headers, response_body, response_data = 0, {}, '', None

    try:
        if use_async:
            response_status, response_headers, response_body = _run_async_coro(
                _do_async_request(api_config.method, url, headers, params, body, body_type, timeout)
            )
        else:
            response_status, response_headers, response_body = _do_sync_request(
                api_config.method, url, headers, params, body, body_type, timeout,
                use_session=use_session, api_id=api_config.id
            )
        try:
            response_data = json.loads(response_body)
        except Exception:
            response_data = response_body
    except requests.exceptions.Timeout:
        error_message = f'同步請求超時 ({timeout}s)'
    except httpx.TimeoutException:
        error_message = f'異步請求超時 ({timeout}s)'
    except Exception as e:
        error_message = str(e)[:400]

    elapsed_ms = round((time.time() - start) * 1000, 2)

    # 提取變量
    extracted = {}
    if response_data is not None and not error_message:
        for rule in api_config.get_extract_vars():
            vn, vp = rule.get('name', '').strip(), rule.get('path', '').strip()
            if vn and vp:
                val = extract_value(response_data, vp)
                if val is not None:
                    extracted[vn] = val
                    set_runtime_var(vn, val)
                    variables[vn] = val

    # HTTP 斷言
    assertion_results, all_http_ok = [], True
    if api_config.get_assertions() and not error_message:
        assertion_results = run_assertions(api_config.get_assertions(), response_status, response_data)
        all_http_ok = all(r['passed'] for r in assertion_results)

    # DeepDiff 斷言
    deepdiff_results, all_dd_ok = [], True
    dd_rules = api_config.get_deepdiff_assertions() if hasattr(api_config, 'get_deepdiff_assertions') else []
    if dd_rules and not error_message:
        deepdiff_results = run_deepdiff_assertions(dd_rules, response_data)
        all_dd_ok = all(r['passed'] for r in deepdiff_results)

    # 後置 SQL
    post_sql_result = ''
    if getattr(api_config, 'post_sql', '') and getattr(api_config, 'post_sql_db_id', None):
        try:
            res = execute_sql_statements(api_config.post_sql_db, replace_vars_in_sql(api_config.post_sql, variables))
            post_sql_result = json.dumps(res, ensure_ascii=False, default=str)
        except Exception as e:
            post_sql_result = json.dumps({'success': False, 'error': str(e)})

    # DB 斷言
    db_assertion_results, all_db_ok = [], True
    db_rules = api_config.get_db_assertions() if hasattr(api_config, 'get_db_assertions') else []
    if db_rules and not error_message:
        # 替換規則中的 {{變量名}}：SQL、expected 值、fields 中的 expected 都支持
        def _replace_db_rules(rules, vars_):
            import copy
            replaced = []
            for rule in rules:
                r = copy.deepcopy(rule)
                if r.get('sql'):
                    r['sql'] = _replace_vars(r['sql'], vars_)
                if r.get('expected') is not None:
                    r['expected'] = _replace_vars(str(r['expected']), vars_)
                if r.get('fields'):
                    for f in r['fields']:
                        if f.get('expected') is not None:
                            f['expected'] = _replace_vars(str(f['expected']), vars_)
                replaced.append(r)
            return replaced
        db_assertion_results = run_db_assertions(_replace_db_rules(db_rules, variables))
        all_db_ok = all(r['passed'] for r in db_assertion_results)
    else:
        db_assertion_results = []

    # 最終狀態
    if error_message:
        status = 'error'
    elif api_config.get_assertions() or dd_rules or db_rules:
        status = 'pass' if (all_http_ok and all_dd_ok and all_db_ok) else 'fail'
    else:
        status = 'pass' if 200 <= response_status < 300 else 'fail'

    return {
        'api_name': api_config.name, 'url': url, 'method': api_config.method,
        'use_async': use_async, 'use_session': use_session, 'body_type': body_type,
        'request_headers': headers, 'request_params': params,
        'request_body': request_body_raw, 'encrypted_body': encrypted_body,
        'enc_applied': enc_applied,
        'pre_redis_log': pre_redis_log,
        'response_status': response_status, 'response_headers': response_headers,
        'response_body': response_body, 'response_data': response_data,
        'response_time': elapsed_ms, 'status': status, 'error_message': error_message,
        'extracted_vars': extracted,
        'assertion_results': assertion_results,
        'deepdiff_results': deepdiff_results,
        'db_assertion_results': db_assertion_results,
        'pre_sql_result': pre_sql_result, 'post_sql_result': post_sql_result,
    }


# ── 批量執行 ─────────────────────────────────────────

def execute_batch(api_ids: list, report_name: str = None):
    from apps.core.models import ApiConfig, TestReport, TestResult
    reset_runtime_vars()
    apis = ApiConfig.objects.filter(id__in=api_ids).order_by('sort_order', 'id')
    if not apis.exists():
        return None
    report_name = report_name or f'批量測試_{time.strftime("%Y%m%d_%H%M%S")}'
    report = TestReport.objects.create(name=report_name, status='running', total=apis.count())
    passed = failed = error = 0
    t0 = time.time()
    for api in apis:
        rd = execute_api(api)
        TestResult.objects.create(
            report=report, api=api,
            api_name=rd['api_name'], url=rd['url'], method=rd['method'],
            use_async=rd['use_async'],
            request_headers=json.dumps(rd['request_headers'], ensure_ascii=False),
            request_params=json.dumps(rd['request_params'], ensure_ascii=False),
            request_body=json.dumps(rd['request_body'], ensure_ascii=False, default=str),
            response_status=rd['response_status'],
            response_headers=json.dumps(rd['response_headers'], ensure_ascii=False),
            response_body=rd['response_body'][:10000],
            response_time=rd['response_time'], status=rd['status'],
            error_message=rd['error_message'],
            extracted_vars=json.dumps(rd['extracted_vars'], ensure_ascii=False, default=str),
            assertion_results=json.dumps(rd['assertion_results'], ensure_ascii=False, default=str),
            db_assertion_results=json.dumps(rd['db_assertion_results'], ensure_ascii=False, default=str),
            deepdiff_results=json.dumps(rd.get('deepdiff_results', []), ensure_ascii=False, default=str),
            pre_sql_result=rd['pre_sql_result'], post_sql_result=rd['post_sql_result'],
        )
        if rd['status'] == 'pass': passed += 1
        elif rd['status'] == 'fail': failed += 1
        else: error += 1
    report.passed = passed; report.failed = failed; report.error = error
    report.duration = round(time.time() - t0, 3); report.status = 'completed'
    report.save()
    return report
