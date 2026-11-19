from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
import uuid
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/sdlc-orchestrator/scripts'))
from ticket_dispatch import dispatch_batch


class Response:
    def __init__(self, data):
        self.data = data

    def json(self):
        return self.data

    def raise_for_status(self):
        pass


class GitLab:
    base_url = 'https://test.example/api/v4/'

    def __init__(self):
        self.notes = {}

    def get(self, path, params=None):
        return Response(self.notes.get(path, []) if params else {'state': 'opened'})

    def post(self, path, json):
        self.notes.setdefault(path, []).append({'author': {'id': 1}, 'body': json['body']})
        return Response({})


class TicketTest(unittest.TestCase):
    def test_three_tickets_two_approved_and_resume(self):
        with tempfile.TemporaryDirectory() as root:
            repo = Path(root) / 'repo'
            subprocess.run(['git', 'init', '-q', str(repo)], check=True)
            for args in [('config', 'user.name', 'Test'), ('config', 'user.email', 't@example.net'),
                         ('commit', '--allow-empty', '-qm', 'base')]:
                subprocess.run(['git', *args], cwd=repo, check=True)
            cfg = {'project_id': 1, 'token_env': 'TEST_TOKEN', 'state_db': root+'/db',
                   'dispatch': {'repository': str(repo), 'worktrees': root+'/trees', 'base_ref': 'HEAD',
                                'approvers': {'analyze-requirements': [9], 'design-system': [9]}}}
            tickets = [{'iid': i, 'revision': 'v1'} for i in (1, 2, 3)]
            api = GitLab()
            def approve(i):
                notes = api.notes[f'projects/1/issues/{i}/notes']
                notes.append({'author': {'id': 9}, 'body': notes[-1]['body'].splitlines()[-1]})
            dispatch_batch(api, cfg, tickets)
            approve(1)
            approve(3)
            result = dispatch_batch(api, cfg, tickets)
            first = result[0]['dispatch']
            self.assertEqual(first['agent'], 'sdlc-requirements')
            self.assertEqual(result[2]['dispatch']['agent'], first['agent'])
            self.assertNotEqual(first['worktree'], result[2]['dispatch']['worktree'])
            self.assertEqual(result[1]['dispatch'], 'waiting for analyze-requirements')
            approve(2)
            cfg['dispatch']['workers'] = 2
            self.assertIn('deferred', dispatch_batch(api, cfg, tickets)[1]['dispatch'])
            folder = Path(first['worktree'])
            checkpoint = folder / 'artifacts/sdlc-progress.md'
            checkpoint.parent.mkdir()
            checkpoint.write_text('requirements reviewed')
            subprocess.run(['git', 'add', '.'], cwd=folder, check=True)
            subprocess.run(['git', 'commit', '-qm', 'stage'], cwd=folder, check=True)
            result = dispatch_batch(api, cfg, tickets[:1], first['assignment'])
            self.assertEqual(result[0]['dispatch'], 'analyze-requirements completed')
            self.assertEqual(dispatch_batch(api, cfg, tickets[:1], first['assignment'])[0]['dispatch'], 'stale completion')
            self.assertIsInstance(dispatch_batch(api, cfg, tickets)[1]['dispatch'], dict)
