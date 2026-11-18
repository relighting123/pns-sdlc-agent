"""Sanitized error/result envelope shared by executable tools."""
import json


def error_result(kind, outcome='not-started', code=None):
    return {'ok': False, 'error': kind, 'outcome': outcome, 'code': code,
            'message': 'Inspect authorized local configuration and service status; raw errors are not exposed.'}


def emit(value):
    print(json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':')))
