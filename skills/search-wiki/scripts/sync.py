"""Resolve a published wiki to an immutable local checkout."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time


def git(*args):
    return subprocess.check_output(['git', *map(str, args)], text=True,
                                   timeout=120, env={**os.environ, 'GIT_TERMINAL_PROMPT':'0'}).strip()


def sync(url, branch, ttl):
    if not (url.startswith(('https://', 'ssh://', 'git@')) or Path(url).is_absolute()):
        raise ValueError('Use HTTPS, SSH or an absolute local Git path')
    git('check-ref-format', 'refs/heads/' + branch)
    key = hashlib.sha256((url + '\n' + branch).encode()).hexdigest()
    root = Path.home() / '.cache' / 'sdlc-wiki' / key
    root.mkdir(parents=True, exist_ok=True)
    stamp = root / 'current'
    old = stamp.read_text().strip() if stamp.exists() else ''
    cached = bool(old and (root / old / 'openwiki').is_dir())
    def result(commit, status):
        return dict(root=str(root / commit), commit=commit, status=status)
    if cached and time.time() - stamp.stat().st_mtime < ttl:
        return result(old, 'cached')
    try:
        ref = 'refs/heads/' + branch
        commit = git('ls-remote', '--exit-code', url, ref).split()[0]
        dest = root / commit
        with tempfile.TemporaryDirectory(dir=root) as tmp:
            path = Path(tmp) / 'repo'
            if not dest.exists():
                git('clone', '--depth', '1', '--single-branch', '--branch', branch, '--', url, path)
                if git('-C', path, 'rev-parse', 'HEAD') != commit or not any((path/'openwiki').rglob('*.md')):
                    raise ValueError('Unpublished wiki or branch changed during clone')
                try:
                    path.rename(dest)
                except OSError:
                    if not dest.is_dir(): raise
            marker = Path(tmp) / 'current'
            marker.write_text(commit)
            marker.replace(stamp)
        return result(commit, 'verified')
    except (ValueError, OSError, subprocess.SubprocessError):
        if cached: return result(old, 'stale-unverified')
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default=os.getenv('SDLC_WIKI_URL'), required=not os.getenv('SDLC_WIKI_URL'))
    parser.add_argument('--branch', default=os.getenv('SDLC_WIKI_BRANCH','main'))
    parser.add_argument('--ttl', type=int, default=3600)
    args = parser.parse_args()
    print(json.dumps(sync(args.url, args.branch, args.ttl)))
