"""Bounded Oracle query CLI. Profiles and approved SQL live outside the plugin."""
import argparse
import base64
import datetime
import decimal
import importlib
import json
import os
from pathlib import Path
import re
import sys
import time


class QueryError(Exception):
    pass


def read_json(path):
    with Path(path).expanduser().open(encoding='utf-8') as stream:
        return json.load(stream)


def integer(value, low, high, field):
    if type(value) is not int or not low <= value <= high:
        raise QueryError('Invalid limit: ' + field)
    return value


def load_profile(config, database):
    profiles = read_json(config).get('databases', {})
    if database not in profiles:
        raise QueryError('Unknown database ID')
    profile = profiles[database]
    if profile.get('mode') not in ('thin', 'thick'):
        raise QueryError('Profile mode must be thin or thick')
    for key in ('dsn_env', 'user_env', 'password_env'):
        if not isinstance(profile.get(key), str) or not os.environ.get(profile[key]):
            raise QueryError('Missing profile credential environment: ' + key)
    return profile


def query_spec(profile, request):
    action = request.get('action')
    binds = request.get('binds', {})
    if not isinstance(binds, dict):
        raise QueryError('binds must be an object')
    if action == 'check':
        return 'SELECT 1 FROM dual', {}, 'check'
    if action == 'describe':
        owner, table = request.get('owner'), request.get('table')
        if owner not in profile.get('metadata_owners', []):
            raise QueryError('Metadata owner is not allowed')
        if not isinstance(table, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_$#]{0,127}', table):
            raise QueryError('Invalid unquoted table name')
        return ('''SELECT column_name, data_type, data_length, data_precision,
                   data_scale, nullable FROM all_tab_columns
                   WHERE owner = :owner AND table_name = :table_name
                   ORDER BY column_id''', {'owner': owner, 'table_name': table.upper()}, 'describe')
    if action != 'query':
        raise QueryError('action must be check, describe or query')
    name = request.get('query')
    if name not in profile.get('allowed_queries', []):
        raise QueryError('Query ID is not allowed for this profile')
    catalog_path = Path(profile['queries_file']).expanduser()
    if not catalog_path.is_absolute():
        raise QueryError('queries_file must be an absolute operator-owned path')
    catalog = read_json(catalog_path)
    spec = catalog.get(name)
    if not isinstance(spec, dict) or not isinstance(spec.get('sql'), str):
        raise QueryError('Missing registered query')
    expected = spec.get('binds', [])
    if set(binds) != set(expected):
        raise QueryError('Bind keys do not match registered query')
    sql = spec['sql'].strip()
    # A conservative syntax guard, not a SQL security parser. Catalog is trusted.
    if not re.match(r'(?is)^SELECT\b', sql) or ';' in sql or re.search(r'(?is)\bFOR\s+UPDATE\b', sql):
        raise QueryError('Registered SQL must be one SELECT without FOR UPDATE')
    return sql, binds, name


def connect(profile):
    driver = importlib.import_module('oracledb')
    if profile['mode'] == 'thick':
        kwargs = {}
        for key in ('lib_dir', 'config_dir'):
            if profile.get(key):
                kwargs[key] = profile[key]
        driver.init_oracle_client(**kwargs)
    kwargs = dict(dsn=os.environ[profile['dsn_env']], user=os.environ[profile['user_env']],
                  password=os.environ[profile['password_env']])
    if profile.get('config_dir'):
        kwargs['config_dir'] = profile['config_dir']
    conn = driver.connect(**kwargs)
    try:
        if bool(conn.thin) != (profile['mode'] == 'thin'):
            raise QueryError('Driver mode differs from requested profile')
        conn.autocommit = False
        conn.call_timeout = integer(profile.get('call_timeout_ms', 15000), 1, 120000, 'call_timeout_ms')
        return conn
    except Exception:
        conn.close()
        raise


def cell(value):
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, decimal.Decimal):
        return str(value)  # Avoid silent decimal precision loss.
    if isinstance(value, (datetime.date, datetime.datetime, datetime.time)):
        return value.isoformat()
    if isinstance(value, datetime.timedelta):
        return str(value)
    if isinstance(value, bytes):
        return {'base64': base64.b64encode(value).decode('ascii')}
    # Do not implicitly read potentially large LOBs or stringify custom objects.
    return {'omitted_type': type(value).__name__}


def run_batch(profile, requests, connection_factory=connect):
    if not isinstance(requests, list) or not 1 <= len(requests) <= 20:
        raise QueryError('requests must contain 1..20 items')
    max_rows = integer(profile.get('max_rows', 100), 1, 5000, 'max_rows')
    max_bytes = integer(profile.get('max_result_bytes', 32000), 512, 1000000, 'max_result_bytes')
    prepared = []
    for request in requests:
        if not isinstance(request, dict):
            raise QueryError('Each request must be an object')
        spec = query_spec(profile, request)
        limit = integer(request.get('max_rows', max_rows), 1, max_rows, 'request.max_rows')
        prepared.append((spec, limit))
    start = time.perf_counter()
    conn = connection_factory(profile)
    connected = time.perf_counter()
    results = []
    used_bytes = 0
    try:
        with conn.cursor() as cursor:
            cursor.execute('SET TRANSACTION READ ONLY')
            for (sql, binds, name), limit in prepared:
                cursor.arraysize = min(limit + 1, 1000)
                cursor.prefetchrows = min(limit + 1, 1000)
                began = time.perf_counter()
                cursor.execute(sql, binds)
                executed = time.perf_counter()
                if cursor.description is None:
                    raise QueryError('Statement did not return a result set')
                columns = [d[0] for d in cursor.description]
                rows = []
                truncated = False
                header_bytes = len(json.dumps(columns, ensure_ascii=False).encode('utf-8'))
                used_bytes += header_bytes
                if used_bytes > max_bytes:
                    raise QueryError('Column metadata exceeds result budget')
                for _ in range(limit + 1):
                    row = cursor.fetchone()
                    if row is None:
                        break
                    if len(rows) == limit:
                        truncated = True
                        break
                    converted = [cell(v) for v in row]
                    size = len(json.dumps(converted, ensure_ascii=False, allow_nan=False).encode('utf-8'))
                    if used_bytes + size > max_bytes:
                        truncated = True
                        break
                    rows.append(converted)
                    used_bytes += size
                results.append(dict(query=name, columns=columns, rows=rows, returned_rows=len(rows),
                                    truncated=truncated, execute_ms=round((executed-began)*1000, 2),
                                    fetch_ms=round((time.perf_counter()-executed)*1000, 2)))
        return dict(ok=True, database_version=conn.version, mode=profile['mode'],
                    connect_ms=round((connected-start)*1000, 2),
                    total_ms=round((time.perf_counter()-start)*1000, 2), results=results)
    finally:
        try:
            conn.rollback()
        finally:
            conn.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default=os.environ.get('ORACLE_QUERY_CONFIG'))
    parser.add_argument('--database', required=True)
    parser.add_argument('--request', required=True, help='JSON request file, or - for stdin')
    args = parser.parse_args()
    try:
        if not args.config:
            raise QueryError('Set --config or ORACLE_QUERY_CONFIG')
        profile = load_profile(args.config, args.database)
        request = json.load(sys.stdin) if args.request == '-' else read_json(args.request)
        result = run_batch(profile, request)
        result['database'] = args.database
        print(json.dumps(result, ensure_ascii=False, allow_nan=False, separators=(',', ':')))
        return 0
    except QueryError as error:
        print(json.dumps({'ok': False, 'error': 'validation', 'message': str(error)}))
    except Exception as error:
        # Raw driver messages may contain hosts, SQL or bind values.
        code = getattr(error.args[0], 'full_code', None) if error.args else None
        code = code if isinstance(code, str) and re.fullmatch(r'(ORA|DPY|DPI)-\d+', code) else None
        print(json.dumps({'ok': False, 'error': 'execution', 'code': code,
                          'message': 'Check dependencies, profile, connectivity, DB permissions and registered SQL locally.'}))
    return 1


if __name__ == '__main__':
    sys.exit(main())
