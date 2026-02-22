"""
MySQL 數據庫工具模塊
- 連接管理（PyMySQL）
- 查詢執行
- SQL 前置/後置
- 數據庫斷言
"""
import re
import json
import logging

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
#  獲取 PyMySQL 連接
# ─────────────────────────────────────────────

def get_connection(db_config):
    """
    根據 DatabaseConfig 對象返回 PyMySQL 連接。
    調用方負責關閉連接。
    """
    try:
        import pymysql
        conn = pymysql.connect(
            host=db_config.host,
            port=int(db_config.port),
            user=db_config.username,
            password=db_config.password,
            database=db_config.database,
            charset=db_config.charset,
            cursorclass=pymysql.cursors.DictCursor,
            connect_timeout=10,
            autocommit=True,
        )
        return conn, None
    except ImportError:
        return None, 'PyMySQL 未安裝，請執行: pip install PyMySQL==1.1.1'
    except Exception as e:
        return None, f'連接失敗: {str(e)}'


def test_connection(db_config):
    """測試數據庫連接，返回 (success: bool, message: str)"""
    conn, err = get_connection(db_config)
    if err:
        return False, err
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT VERSION() AS ver')
            row = cur.fetchone()
            ver = row.get('ver', '未知') if row else '未知'
        return True, f'連接成功，MySQL 版本: {ver}'
    except Exception as e:
        return False, f'查詢失敗: {str(e)}'
    finally:
        conn.close()


# ─────────────────────────────────────────────
#  執行任意 SQL（支持多條，分號分隔）
# ─────────────────────────────────────────────

def execute_sql_statements(db_config, sql_text: str) -> dict:
    """
    執行一條或多條 SQL 語句（用分號分隔）。
    返回:
      {
        "success": bool,
        "statements": [
          {"sql": "...", "type": "SELECT|DML|DDL", "rows": [...], "affected": 0, "error": ""}
        ],
        "error": ""   # 整體錯誤
      }
    """
    conn, err = get_connection(db_config)
    if err:
        return {'success': False, 'statements': [], 'error': err}

    # 分割語句，過濾空行和純注釋
    raw_stmts = [s.strip() for s in sql_text.split(';') if s.strip()]
    results = []

    try:
        with conn.cursor() as cur:
            for stmt in raw_stmts:
                item = {'sql': stmt, 'type': _sql_type(stmt), 'rows': [], 'affected': 0, 'error': ''}
                try:
                    cur.execute(stmt)
                    if item['type'] == 'SELECT':
                        rows = cur.fetchall()
                        # 將所有值轉換為字符串，確保 JSON 序列化安全
                        item['rows'] = [{k: str(v) if v is not None else None for k, v in r.items()} for r in rows]
                        item['affected'] = len(rows)
                    else:
                        item['affected'] = cur.rowcount
                except Exception as e:
                    item['error'] = str(e)
                results.append(item)
    except Exception as e:
        return {'success': False, 'statements': results, 'error': str(e)}
    finally:
        conn.close()

    all_ok = all(not r['error'] for r in results)
    return {'success': all_ok, 'statements': results, 'error': ''}


def _sql_type(stmt: str) -> str:
    kw = stmt.strip().upper().split()[0] if stmt.strip() else ''
    if kw == 'SELECT':
        return 'SELECT'
    if kw in ('INSERT', 'UPDATE', 'DELETE', 'REPLACE'):
        return 'DML'
    return 'DDL'


# ─────────────────────────────────────────────
#  數據庫斷言
# ─────────────────────────────────────────────
# 規則格式:
# {
#   "db_id": 1,
#   "sql": "SELECT count(*) as cnt FROM orders WHERE status='pending'",
#   "field": "cnt",        -- 取結果集第一行的哪個字段（SELECT結果）
#   "expected": "0",       -- 期望值（字符串比較）
#   "operator": "=="       -- ==  !=  >  <  >=  <=  contains  not_empty
# }

OPERATORS = {
    '==':       lambda a, e: str(a) == str(e),
    '!=':       lambda a, e: str(a) != str(e),
    '>':        lambda a, e: _to_num(a) > _to_num(e),
    '<':        lambda a, e: _to_num(a) < _to_num(e),
    '>=':       lambda a, e: _to_num(a) >= _to_num(e),
    '<=':       lambda a, e: _to_num(a) <= _to_num(e),
    'contains': lambda a, e: str(e) in str(a),
    'not_empty':lambda a, e: a is not None and str(a) != '' and str(a) != '0',
}

def _to_num(v):
    try:
        return float(v)
    except Exception:
        return 0.0


def run_db_assertions(rules: list) -> list:
    """
    批量執行數據庫斷言，支持單字段（舊格式）和多字段（新格式）。

    舊格式（兼容）:
        {
          "db_id": 1,
          "sql": "SELECT count(*) as cnt FROM users WHERE id=1",
          "field": "cnt",
          "operator": "==",
          "expected": "1",
          "label": "可選描述"
        }

    新格式（多字段）:
        {
          "db_id": 1,
          "sql": "SELECT name, status, age FROM users WHERE id=1",
          "fields": [
              {"field": "name",   "operator": "==",       "expected": "張三"},
              {"field": "status", "operator": "==",       "expected": "1"},
              {"field": "age",    "operator": ">=",       "expected": "18"},
              {"field": "name",   "operator": "contains", "expected": "張"}
          ],
          "label": "用戶狀態斷言"
        }

    返回：每條規則生成一個結果項（多字段時 passed=所有子字段均通過）。
    """
    from apps.core.models import DatabaseConfig

    results = []
    conn_cache = {}

    try:
        for rule in rules:
            db_id = rule.get('db_id')
            sql   = rule.get('sql', '').strip()
            label = rule.get('label', '') or (sql[:60] if sql else '未命名斷言')

            # ── 統一構建 field_checks 列表 ──
            # 支持新格式 "fields" 或舊格式 "field"+"operator"+"expected"
            raw_fields = rule.get('fields')
            if raw_fields and isinstance(raw_fields, list):
                field_checks = raw_fields
            else:
                # 舊格式單字段
                field_checks = [{
                    'field':    rule.get('field', ''),
                    'operator': rule.get('operator', '=='),
                    'expected': rule.get('expected', ''),
                }]

            item = {
                'rule':          rule,
                'sql':           sql,
                'label':         label,
                'row':           None,           # 查詢結果行（dict）
                'field_results': [],             # 每個字段的子斷言結果
                'passed':        False,
                'message':       '',
            }

            if not db_id or not sql:
                item['message'] = '規則不完整：缺少 db_id 或 sql'
                results.append(item)
                continue

            # ── 獲取/緩存連接 ──
            if db_id not in conn_cache:
                try:
                    db_conf = DatabaseConfig.objects.get(pk=db_id)
                    conn, err = get_connection(db_conf)
                    conn_cache[db_id] = (conn, err)
                except DatabaseConfig.DoesNotExist:
                    conn_cache[db_id] = (None, f'數據庫配置 id={db_id} 不存在')

            conn, conn_err = conn_cache[db_id]
            if conn_err:
                item['message'] = conn_err
                results.append(item)
                continue

            # ── 執行 SQL ──
            try:
                with conn.cursor() as cur:
                    cur.execute(sql)
                    row = cur.fetchone()   # DictCursor → dict or None
            except Exception as e:
                item['message'] = f'SQL 執行錯誤: {str(e)}'
                results.append(item)
                continue

            item['row'] = row

            # ── 逐字段斷言 ──
            sub_results = []
            for fc in field_checks:
                field_name = fc.get('field', '').strip()
                operator   = fc.get('operator', '==')
                expected   = fc.get('expected', '')

                # 取字段值
                if row is None:
                    actual = None
                elif field_name and isinstance(row, dict) and field_name in row:
                    actual = row[field_name]
                elif field_name and isinstance(row, dict):
                    # 字段名不存在
                    actual = None
                elif row and isinstance(row, dict):
                    # 未指定字段名：取第一個字段
                    actual = list(row.values())[0]
                else:
                    actual = None

                op_fn  = OPERATORS.get(operator, OPERATORS['=='])
                passed = op_fn(actual, expected) if actual is not None else (operator == 'not_empty' and False or False)

                sub_item = {
                    'field':    field_name,
                    'actual':   str(actual) if actual is not None else None,
                    'expected': expected,
                    'operator': operator,
                    'passed':   passed,
                    'message':  (
                        f'字段[{field_name or "第1列"}]='
                        f'{actual} {operator} {expected} → '
                        f'{"✓ 通過" if passed else "✗ 失敗"}'
                    ),
                }
                sub_results.append(sub_item)

            item['field_results'] = sub_results
            item['passed']        = bool(sub_results) and all(s['passed'] for s in sub_results)
            # 彙總消息
            if len(sub_results) == 1:
                item['message'] = f'[DB] {label} → {sub_results[0]["message"]}'
            else:
                detail = ' | '.join(s['message'] for s in sub_results)
                overall = '✓ 全部通過' if item['passed'] else f'✗ {sum(1 for s in sub_results if not s["passed"])}/{len(sub_results)} 失敗'
                item['message'] = f'[DB] {label} → {overall} | {detail}'

            results.append(item)

    finally:
        for conn_obj, _ in conn_cache.values():
            if conn_obj:
                try: conn_obj.close()
                except Exception: pass

    return results
