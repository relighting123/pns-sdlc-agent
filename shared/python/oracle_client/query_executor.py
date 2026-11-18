"""Registered read execution with bounded output."""
import json
import re
import time
import base64
import datetime
import decimal
from pathlib import Path
from .common import QueryError, read_json, integer
from .connections import connect, load_profile
from execution_policy.local_role import authorize
from execution_policy import require_effect

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
    require_effect(spec, 'read')
    expected = spec.get('binds', [])
    if set(binds) != set(expected):
        raise QueryError('Bind keys do not match registered query')
    sql = spec['sql'].strip()
    # A conservative syntax guard, not a SQL security parser. Catalog is trusted.
    if not re.match(r'(?is)^SELECT\b', sql) or ';' in sql or re.search(r'(?is)\bFOR\s+UPDATE\b', sql):
        raise QueryError('Registered SQL must be one SELECT without FOR UPDATE')
    return sql, binds, name


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
    authorize(profile, "read")
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
