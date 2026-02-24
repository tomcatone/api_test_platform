"""
Redis 工具模塊
功能：
  1. 連接管理
  2. 連通性測試
  3. KEY 讀取/寫入/刪除/掃描
  4. 獲取驗證碼 → 自動存入全局變量
  5. 批量掃描 Keys（支持 Pattern）
"""
import json
import logging

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
#  獲取 Redis 客戶端
# ─────────────────────────────────────────────

def get_client(redis_config):
    """
    根據 RedisConfig 對象返回 redis.Redis 客戶端。
    返回 (client, error_str)
    """
    try:
        import redis
        client = redis.Redis(
            host=redis_config.host,
            port=int(redis_config.port),
            password=redis_config.password or None,
            db=int(redis_config.db),
            decode_responses=True,      # 自動解碼為字符串
            socket_connect_timeout=5,
            socket_timeout=5,
        )
        client.ping()                   # 驗證連接
        return client, None
    except ImportError:
        return None, 'redis 庫未安裝，請執行: pip install redis==5.2.1'
    except Exception as e:
        return None, f'Redis 連接失敗: {str(e)}'


def test_connection(redis_config):
    """測試連接，返回 (success, message)"""
    client, err = get_client(redis_config)
    if err:
        return False, err
    try:
        info = client.info('server')
        ver = info.get('redis_version', '未知')
        return True, f'連接成功，Redis 版本: {ver}'
    except Exception as e:
        return False, f'獲取信息失敗: {str(e)}'
    finally:
        client.close()


# ─────────────────────────────────────────────
#  基礎操作
# ─────────────────────────────────────────────

def redis_get(redis_config, key: str) -> dict:
    """
    GET key，返回值和類型
    支持 String / Hash / List / Set / ZSet
    """
    client, err = get_client(redis_config)
    if err:
        return {'success': False, 'error': err, 'key': key, 'value': None, 'type': None, 'ttl': -1}
    try:
        key_type = client.type(key)
        ttl = client.ttl(key)

        if key_type == 'none':
            return {'success': True, 'key': key, 'value': None, 'type': 'none', 'ttl': ttl,
                    'message': f'Key [{key}] 不存在'}

        if key_type == 'string':
            value = client.get(key)
        elif key_type == 'hash':
            value = client.hgetall(key)
        elif key_type == 'list':
            value = client.lrange(key, 0, -1)
        elif key_type == 'set':
            value = list(client.smembers(key))
        elif key_type == 'zset':
            value = client.zrange(key, 0, -1, withscores=True)
            value = [{'member': m, 'score': s} for m, s in value]
        else:
            value = client.get(key)

        return {
            'success': True, 'key': key, 'value': value,
            'type': key_type, 'ttl': ttl, 'error': ''
        }
    except Exception as e:
        return {'success': False, 'key': key, 'value': None, 'type': None, 'ttl': -1, 'error': str(e)}
    finally:
        client.close()


def redis_set(redis_config, key: str, value: str, ttl: int = None) -> dict:
    """SET key value [EX ttl]"""
    client, err = get_client(redis_config)
    if err:
        return {'success': False, 'error': err}
    try:
        if ttl and int(ttl) > 0:
            client.setex(key, int(ttl), value)
        else:
            client.set(key, value)
        return {'success': True, 'key': key, 'message': f'設置成功'}
    except Exception as e:
        return {'success': False, 'error': str(e)}
    finally:
        client.close()


def redis_delete(redis_config, keys: list) -> dict:
    """DEL key [key ...]"""
    client, err = get_client(redis_config)
    if err:
        return {'success': False, 'error': err}
    try:
        count = client.delete(*keys)
        return {'success': True, 'deleted': count, 'message': f'刪除 {count} 個 Key'}
    except Exception as e:
        return {'success': False, 'error': str(e)}
    finally:
        client.close()


def redis_scan(redis_config, pattern: str = '*', count: int = 100) -> dict:
    """SCAN 掃描匹配的 Keys"""
    client, err = get_client(redis_config)
    if err:
        return {'success': False, 'error': err, 'keys': []}
    try:
        keys = []
        cursor = 0
        while True:
            cursor, batch = client.scan(cursor, match=pattern, count=count)
            keys.extend(batch)
            if cursor == 0 or len(keys) >= 200:     # 最多返回200個
                break
        return {'success': True, 'pattern': pattern, 'keys': sorted(keys), 'total': len(keys)}
    except Exception as e:
        return {'success': False, 'error': str(e), 'keys': []}
    finally:
        client.close()


def redis_ttl(redis_config, key: str) -> dict:
    """查詢 TTL"""
    client, err = get_client(redis_config)
    if err:
        return {'success': False, 'error': err}
    try:
        ttl = client.ttl(key)
        return {'success': True, 'key': key, 'ttl': ttl,
                'message': '永久' if ttl == -1 else ('不存在' if ttl == -2 else f'{ttl}秒後過期')}
    except Exception as e:
        return {'success': False, 'error': str(e)}
    finally:
        client.close()


def redis_expire(redis_config, key: str, ttl: int) -> dict:
    """EXPIRE key seconds"""
    client, err = get_client(redis_config)
    if err:
        return {'success': False, 'error': err}
    try:
        result = client.expire(key, int(ttl))
        return {'success': True, 'key': key, 'result': result, 'message': f'已設置 {ttl}秒 TTL'}
    except Exception as e:
        return {'success': False, 'error': str(e)}
    finally:
        client.close()


# ─────────────────────────────────────────────
#  驗證碼專用：獲取並存入全局變量
# ─────────────────────────────────────────────

def fetch_captcha_to_global(redis_config_id: int, redis_key: str,
                             var_name: str, extract_field: str = None) -> dict:
    """
    從 Redis 獲取驗證碼，存入全局變量供接口使用。

    redis_key:      Redis 中存儲驗證碼的 Key（支持{{變量名}}佔位）
    var_name:       存入全局變量的名稱
    extract_field:  如果值是 JSON，提取其中某個字段（如 code）

    返回:
      { success, value, var_name, message }
    """
    from apps.core.models import RedisConfig, GlobalVariable
    from apps.core.executor import load_global_vars, _replace_vars

    try:
        cfg = RedisConfig.objects.get(pk=redis_config_id)
    except RedisConfig.DoesNotExist:
        return {'success': False, 'error': f'Redis 配置 id={redis_config_id} 不存在'}

    # 支持 key 中使用 {{變量名}}
    variables = load_global_vars()
    real_key = _replace_vars(redis_key, variables)

    result = redis_get(cfg, real_key)
    if not result['success']:
        return {'success': False, 'error': result['error']}

    raw_value = result['value']
    if raw_value is None:
        return {'success': False, 'error': f'Key [{real_key}] 不存在或已過期', 'key': real_key}

    # 嘗試解析 JSON 並提取字段
    final_value = raw_value
    if extract_field:
        try:
            data = json.loads(raw_value) if isinstance(raw_value, str) else raw_value
            if isinstance(data, dict) and extract_field in data:
                final_value = str(data[extract_field])
            else:
                return {'success': False, 'error': f'JSON 字段 [{extract_field}] 不存在，原始值: {raw_value}'}
        except Exception:
            final_value = raw_value     # 非 JSON，原樣使用

    # 存入全局變量
    GlobalVariable.objects.update_or_create(
        name=var_name,
        defaults={
            'value': str(final_value),
            'var_type': 'string',
            'description': f'Redis 驗證碼 key={real_key}',
        }
    )

    # 同步運行時變量
    from apps.core.executor import set_runtime_var
    set_runtime_var(var_name, str(final_value))

    logger.info(f'[Redis驗證碼] key={real_key} → {var_name}={final_value}')
    return {
        'success': True,
        'key': real_key,
        'raw_value': str(raw_value),
        'extracted_value': str(final_value),
        'var_name': var_name,
        'ttl': result['ttl'],
        'message': f'已獲取並存入變量 {{{{ {var_name} }}}}'
    }
