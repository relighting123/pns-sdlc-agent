"""Single registered DML with explicit intent and row-count check."""
import re
import time
from pathlib import Path
from execution_policy import require_effect
from .common import QueryError, integer, read_json
from .connections import connect


class CommitUnknown(QueryError):
    pass


def prepare(profile, request, apply=False):
    if not isinstance(request, dict) or set(request) - {'operation','binds','expected_rows'}:
        raise QueryError('Invalid write request')
    name = request.get('operation')
    if name not in profile.get('allowed_writes', []):
        raise QueryError('Write operation is not allowed')
    path = Path(profile['writes_file']).expanduser()
    if not path.is_absolute():
        raise QueryError('writes_file must be an absolute path')
    spec = read_json(path).get(name)
    if not isinstance(spec, dict):
        raise QueryError('Missing registered write')
    require_effect(spec, 'write', profile.get('allow_write'), apply)
    sql = spec.get('sql', '').strip()
    if not re.match(r'(?is)^(INSERT\s+INTO|UPDATE|DELETE\s+FROM)\b', sql) or ';' in sql:
        raise QueryError('Only a single registered INSERT, UPDATE or DELETE is supported')
    binds = request.get('binds', {})
    if not isinstance(binds, dict) or set(binds) != set(spec.get('binds', [])):
        raise QueryError('Write bind keys do not match')
    maximum = integer(profile.get('max_write_rows', 100), 1, 10000, 'max_write_rows')
    expected = integer(request.get('expected_rows'), 0, maximum, 'expected_rows')
    return name, sql, binds, expected


def run_write(profile, request, apply=False, connection_factory=connect):
    name, sql, binds, expected = prepare(profile, request, apply)
    began = time.perf_counter()
    conn = connection_factory(profile)
    commit_attempted = False
    committed = False
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql, binds)
            affected = cursor.rowcount
            if affected != expected:
                raise QueryError('Affected rows differ from expected_rows; transaction rolled back')
        commit_attempted = True
        try:
            conn.commit()
        except Exception as error:
            raise CommitUnknown('Commit acknowledgement unavailable; reconcile before any retry') from error
        committed = True
        return dict(ok=True, outcome='committed', operation=name, affected_rows=affected,
                    database_version=conn.version, mode=profile['mode'],
                    elapsed_ms=round((time.perf_counter()-began)*1000,2))
    finally:
        try:
            if not committed:
                try:
                    conn.rollback()
                except Exception:
                    if not commit_attempted:
                        raise
        finally:
            conn.close()
