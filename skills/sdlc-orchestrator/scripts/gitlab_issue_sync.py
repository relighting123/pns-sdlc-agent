"""Synchronize a requirements-agent handoff to GitLab."""
import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'shared/python'))
import httpx
from credential_store import resolve
from itsm_handoff import validate_requests

END = '<!-- /sdlc-itsm -->'


def synchronize(client, db, config, request):
    identity = json.dumps([config['source'], request['request_id']], ensure_ascii=False)
    digest = hashlib.sha256(identity.encode()).hexdigest()
    marker = f'<!-- sdlc-itsm:{digest} -->'
    label = f'sdlc-itsm-{digest}'
    path = f"projects/{config['project_id']}/issues"
    # Code indentation keeps source content inert in the issue description.
    source = '\n'.join('    ' + line for line in (
        f"ITSM 요청: {request['request_id']}\n버전: {request['revision']}\n"
        f"제목: {request['title']}\n\n{request['summary']}").splitlines())
    block = f'{marker}\n\n{source}\n\n{END}'
    response = client.get(path, params={'labels': label, 'scope': 'all', 'per_page': 2})
    response.raise_for_status()
    issues = response.json()
    if len(issues) > 1:
        raise ValueError('Multiple GitLab issues share the ITSM key')
    key = (str(client.base_url), config['project_id'], digest)
    if issues:
        issue, = issues
        description = issue['description'] or ''
        before, found, region = description.partition(marker)
        _, closed, after = region.partition('\n\n' + END)
        if not found or not closed:
            raise ValueError('GitLab issue is missing its managed ITSM block')
        updated = before + block + after
        status = 'existing'
        if updated != description:
            client.put(f"{path}/{issue['iid']}", json={'description': updated}).raise_for_status()
            status = 'updated'
    else:
        # Persist the attempt before POST. A timeout can still have created an issue.
        with db:
            claim = db.execute('INSERT OR IGNORE INTO issue_claim VALUES (?, ?, ?)', key)
        if claim.rowcount != 1:
            raise ValueError('Previous create attempt needs GitLab reconciliation')
        response = client.post(path, json={
            'title': request['title'], 'description': block, 'labels': label,
        })
        response.raise_for_status()
        issue = response.json()
        status = 'created'
    # Keep the claim after a successful create so a missing label cannot cause a second POST.
    with db:
        db.execute('INSERT OR IGNORE INTO issue_claim VALUES (?, ?, ?)', key)
    return {'iid': issue['iid'], 'url': issue['web_url'], 'status': status, **request}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument("--dispatch", action="store_true", help="Run eligible ticket stages after intake")
    parser.add_argument("--complete", metavar="ASSIGNMENT", help="Record one verified native stage result")
    parser.add_argument("--intake", required=True, type=Path, help="Validated handoff from the requirements agent")
    args = parser.parse_args()
    try:
        config = json.loads(args.config.read_text(encoding='utf-8'))
        base = urlsplit(config['gitlab_url'])
        if (base.scheme != 'https' or not base.hostname or base.username or base.password
                or base.query or base.fragment or type(config['project_id']) is not int
                or config['project_id'] < 1):
            raise ValueError('Expected HTTPS GitLab URL and numeric project ID')
        if type(config['batch_size']) is not int or not 1 <= config['batch_size'] <= 100:
            raise ValueError('Batch size must be between 1 and 100')
        token = resolve(config, 'token')
        if not token:
            raise ValueError('Missing GitLab token')
        state = Path(config['state_db']).expanduser()
        if not state.is_absolute():
            raise ValueError('state_db must be absolute')
        requests = validate_requests(json.loads(args.intake.read_text(encoding="utf-8")), config["batch_size"])
        failures = 0
        with closing(sqlite3.connect(state)) as db, httpx.Client(
            base_url=config['gitlab_url'].rstrip('/') + '/api/v4/',
            headers={'PRIVATE-TOKEN': token}, timeout=20, follow_redirects=False,
        ) as client:
            with db:
                db.execute('CREATE TABLE IF NOT EXISTS issue_claim ('
                           'host TEXT, project INTEGER, digest TEXT, PRIMARY KEY(host, project, digest))')
            tickets = []
            for index, request in enumerate(requests, start=1):
                try:
                    ticket = synchronize(client, db, config, request)
                    tickets.append(ticket)
                    print(json.dumps(ticket, ensure_ascii=False))
                except httpx.HTTPStatusError as error:
                    failures += 1
                    print(f'Row {index}: GitLab HTTP {error.response.status_code}', file=sys.stderr)
                except (ValueError, httpx.RequestError) as error:
                    failures += 1
                    message = str(error) if type(error) is ValueError else type(error).__name__
                    print(f'Row {index}: {message}', file=sys.stderr)
            if args.dispatch or args.complete:
                from ticket_dispatch import dispatch_batch
                for result in dispatch_batch(client, config, tickets, args.complete):
                    failures += int("error" in result)
                    print(json.dumps(result))
        return int(bool(failures))
    except Exception as error:
        print(f'ITSM batch failed: {type(error).__name__}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
