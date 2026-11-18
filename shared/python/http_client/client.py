"""Catalog-driven HTTP execution. Client lifetime scopes connection reuse."""
import json
import os
import random
import re
import ssl
import time
from pathlib import Path
from urllib.parse import quote, urlsplit

import httpx
from jsonschema import Draft202012Validator
from execution_policy import PolicyError, bounded_int, require_effect
from execution_result import error_result


def load_json(path):
    return json.loads(Path(path).expanduser().read_text(encoding='utf-8'))


class HttpClient:
    def __init__(self, profile, catalog, *, transport=None, sleep=time.sleep):
        self.profile, self.catalog, self.sleep = profile, catalog, sleep
        base = os.environ.get(profile.get('base_url_env', ''), '')
        parsed = urlsplit(base)
        if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
                or parsed.query or parsed.fragment):
            raise PolicyError('Base URL must be HTTPS with no credentials, query or fragment')
        self.base = base.rstrip('/')
        self.budget = bounded_int(profile.get('max_response_bytes', 32000), 512, 1000000, 'max_response_bytes')
        self.input_budget = bounded_int(profile.get('max_request_bytes', 32000), 512, 1000000, 'max_request_bytes')
        self.attempts = bounded_int(profile.get('max_read_attempts', 2), 1, 4, 'max_read_attempts')
        def timeout(name, default):
            return bounded_int(profile.get(name, default), 1, 120, name)
        headers = {'Accept': 'application/json'}
        auth = profile.get('auth', {'type': 'none'})
        kind = auth.get('type')
        if kind in ('bearer', 'header'):
            value = os.environ.get(auth.get('token_env',''))
            if not value or '\r' in value or '\n' in value:
                raise PolicyError('Missing or invalid credential environment')
            header = 'Authorization' if kind == 'bearer' else auth.get('header','')
            if not re.fullmatch(r'[A-Za-z][A-Za-z0-9-]*', header) or header.lower() in ('host','content-length','connection'):
                raise PolicyError('Invalid authentication header')
            headers[header] = 'Bearer ' + value if kind == 'bearer' else value
        elif kind != 'none':
            raise PolicyError('Unsupported authentication type')
        context = ssl.create_default_context(cafile=profile.get('ca_file'))
        if profile.get('client_cert'):
            context.load_cert_chain(profile['client_cert'], profile.get('client_key'))
        self.client = httpx.Client(headers=headers, verify=context, trust_env=False,
            proxy=profile.get('proxy'), follow_redirects=False,
            timeout=httpx.Timeout(connect=timeout('connect_timeout_s', 5), read=timeout('read_timeout_s', 15),
                                  write=timeout('write_timeout_s', 15), pool=timeout('pool_timeout_s', 5)),
            limits=httpx.Limits(max_connections=4, max_keepalive_connections=2), transport=transport)

    def __enter__(self): return self
    def __exit__(self, *args): self.client.close()

    def prepare(self, request, effect, apply):
        if not isinstance(request, dict) or set(request) - {'operation','path','query','body'}:
            raise PolicyError('Unexpected request fields')
        operation = request.get('operation')
        if operation not in self.profile.get('allowed_operations', []):
            raise PolicyError('Operation is not allowed')
        spec = self.catalog.get(operation)
        if not isinstance(spec, dict):
            raise PolicyError('Unknown operation')
        require_effect(spec, effect, self.profile.get('allow_write'), apply)
        method = spec.get('method', '').upper()
        if method not in ('GET','POST','PUT','PATCH','DELETE','HEAD','OPTIONS'):
            raise PolicyError('Unsupported method')
        path = spec.get('path', '')
        if not path.startswith('/') or path.startswith('//') or any(c in path for c in ('?', '#', '\\', '%')):
            raise PolicyError('Invalid registered path')
        params = {'path': request.get('path', {}), 'query': request.get('query', {}), 'body': request.get('body')}
        schema = spec.get('request_schema')
        if not isinstance(schema, dict):
            raise PolicyError('An explicit request_schema is required')
        Draft202012Validator.check_schema(schema)
        if not Draft202012Validator(schema).is_valid(params):
            raise PolicyError('Request does not match registered schema')
        values = params['path']
        if not isinstance(values, dict) or set(re.findall(r'\{([A-Za-z_][A-Za-z0-9_]*)\}', path)) != set(values):
            raise PolicyError('Path parameters do not match registered path')
        for key, value in values.items():
            value = str(value)
            if value in ('.','..') or not value or any(c in value for c in ('/','\\','%', '?','#')):
                raise PolicyError('Unsafe path parameter')
            path = path.replace('{'+key+'}', quote(value, safe=''))
        if any(part in ('.','..') for part in path.split('/')) or '{' in path or '}' in path:
            raise PolicyError('Unsafe registered path')
        url = self.base + path
        if urlsplit(url).netloc != urlsplit(self.base).netloc:
            raise PolicyError('Request escaped configured host')
        if len(json.dumps(params, allow_nan=False).encode()) > self.input_budget:
            raise PolicyError('Request exceeds budget')
        return spec, method, url, params

    def request(self, request, *, effect='read', apply=False):
        spec, method, url, params = self.prepare(request, effect, apply)
        attempts = self.attempts if effect == 'read' and spec.get('retry_safe') is True else 1
        began = time.perf_counter()
        for attempt in range(1, attempts + 1):
            wait = None
            try:
                with self.client.stream(method, url, params=params['query'], json=params['body']) as response:
                    status = response.status_code
                    if status in (429,502,503,504) and attempt < attempts:
                        retry_after = response.headers.get('Retry-After','')
                        if retry_after.isdigit() and int(retry_after) > 5:
                            return dict(error_result('retry-after-too-long', 'failed'), status=status, attempts=attempt)
                        wait = int(retry_after) if retry_after.isdigit() else min(2 ** (attempt-1) + random.random(), 5)
                    elif not 200 <= status < 300:
                        return dict(error_result('http-status', 'unknown' if effect=='write' else 'failed'),
                                    status=status, attempts=attempt, elapsed_ms=round((time.perf_counter()-began)*1000,2))
                    else:
                        data = bytearray()
                        for chunk in response.iter_bytes(chunk_size=4096):
                            if len(data) + len(chunk) > self.budget:
                                return dict(ok=True, outcome='accepted' if effect=='write' else 'read',
                                            status=status, body=None, truncated=True, attempts=attempt,
                                            elapsed_ms=round((time.perf_counter()-began)*1000,2))
                            data.extend(chunk)
                        body = None
                        if data:
                            try: body = json.loads(data)
                            except (ValueError, UnicodeError):
                                return dict(error_result('non-json-response', 'unknown' if effect=='write' else 'failed'),status=status)
                        fields = spec.get('response_fields')
                        if fields is not None and isinstance(body, dict):
                            body = {k: body[k] for k in fields if k in body}
                        return dict(ok=True, outcome='accepted' if effect=='write' else 'read', status=status,
                                    body=body, truncated=False, attempts=attempt,
                                    elapsed_ms=round((time.perf_counter()-began)*1000,2))
            except httpx.TransportError:
                if attempt == attempts:
                    return dict(error_result('transport', 'unknown' if effect=='write' else 'failed'), attempts=attempt)
                wait = min(2 ** (attempt-1) + random.random(), 5)
            self.sleep(wait)
        raise AssertionError('Unreachable retry state')
