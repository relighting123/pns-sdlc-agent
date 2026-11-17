"""Bounded, script-first requirement intake; never executes remote instructions."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

from .contracts import ContractError, digest, inside
from .context import redact


def pointer(value, path):
    if not isinstance(path, str) or (path and not path.startswith('/')):
        raise ContractError('Mappings must be JSON pointers')
    try:
        for part in path.split('/')[1:] if path else []:
            part = part.replace('~1', '/').replace('~0', '~')
            value = value[int(part)] if isinstance(value, list) else value[part]
        return value
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise ContractError(f'Missing mapped field: {path}') from exc


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ContractError('API redirects are disabled; configure the final endpoint')


def collect(config: dict, response: Path | None = None) -> dict:
    if not isinstance(config, dict) or not isinstance(config.get('source'), str) or not config['source'].strip():
        raise ContractError('A stable source name is required')
    limit = config.get('max_bytes', 2_000_000)
    timeout = config.get('timeout_seconds', 30)
    if type(limit) is not int or not 1 <= limit <= 20_000_000:
        raise ContractError('max_bytes must be 1..20000000')
    if type(timeout) is not int or not 1 <= timeout <= 120:
        raise ContractError('timeout_seconds must be 1..120')
    fields = config.get('fields', {})
    if not isinstance(fields, dict) or not {'id', 'title', 'description'} <= fields.keys():
        raise ContractError('Map id, title and description fields')
    if set(fields) - {'id', 'title', 'description', 'acceptance'}:
        raise ContractError('Unknown intake field')
    if response is not None:
        with response.open('rb') as stream:
            raw = stream.read(limit + 1)
    else:
        endpoint = config.get('url', '')
        url = urlsplit(endpoint)
        if url.scheme != 'https' or not url.hostname or url.username or url.password or url.fragment:
            raise ContractError('API URL must be HTTPS without embedded credentials or fragment')
        headers = {'Accept': 'application/json'}
        token_env = config.get('bearer_token_env')
        if token_env:
            token = os.environ.get(token_env)
            if not token:
                raise ContractError('API token environment variable is unset')
            if '\r' in token or '\n' in token:
                raise ContractError('Invalid API token')
            headers['Authorization'] = 'Bearer ' + token
        try:
            opener = urllib.request.build_opener(NoRedirect())
            with opener.open(urllib.request.Request(endpoint, headers=headers), timeout=timeout) as stream:
                raw = stream.read(limit + 1)
        except (urllib.error.URLError, TimeoutError) as exc:
            raise ContractError('API request failed; check endpoint, authorization and availability') from exc
    if len(raw) > limit:
        raise ContractError('API response exceeds max_bytes')
    try:
        payload = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise ContractError('API response must be valid JSON') from exc
    items = pointer(payload, config.get('items_pointer', ''))
    if not isinstance(items, list) or not 1 <= len(items) <= 1000:
        raise ContractError('Expected 1..1000 requirement records; collect pagination explicitly')
    records = {}
    for item in items:
        mapped = {key: pointer(item, path) for key, path in fields.items()}
        if type(mapped['id']) not in (str, int) or not str(mapped['id']).strip():
            raise ContractError('Source id must be a nonempty string or integer')
        for key in ('title', 'description'):
            if not isinstance(mapped[key], str) or not mapped[key].strip():
                raise ContractError(f'{key} must be nonempty text')
        acceptance = mapped.get('acceptance', [])
        if not isinstance(acceptance, list) or not all(isinstance(x, str) and x.strip() for x in acceptance):
            raise ContractError('acceptance must be a string array')
        source_id = str(mapped['id'])
        record = {'id': 'REQ-' + digest([config['source'], source_id])[:16].upper(),
                  'source': config['source'], 'source_id': source_id,
                  'title': redact(mapped['title']), 'description': redact(mapped['description']),
                  'acceptance': [redact(x) for x in acceptance]}
        if source_id in records and records[source_id] != record:
            raise ContractError('Conflicting duplicate source id')
        records[source_id] = record
    return {'version': 1, 'source': config['source'], 'response_sha256': __import__('hashlib').sha256(raw).hexdigest(),
            'requirements': sorted(records.values(), key=lambda r: r['id'])}


def save(root: Path, artifact: dict) -> str:
    # Immutable snapshot: no timestamp churn, no silently overwritten provenance.
    name = 'inputs/requirements/' + digest(artifact)[:24] + '.json'
    target = inside(root.resolve(), name)
    target.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(artifact, ensure_ascii=False, sort_keys=True, indent=2) + '\n'
    try:
        with target.open('x', encoding='utf-8') as stream:
            stream.write(content)
    except FileExistsError:
        if target.read_text(encoding='utf-8') != content:
            raise ContractError('Existing intake artifact differs')
    return name
