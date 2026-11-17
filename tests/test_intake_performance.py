import copy
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sdlc_agent.cli import default_workflow, main
from sdlc_agent.context import build
from sdlc_agent.contracts import ContractError, validate_workflow
from sdlc_agent.intake import collect, save, NoRedirect
from sdlc_agent.performance import normalize_usage, summarize
from sdlc_agent.store import Store
from sdlc_agent.workspace import git


class IntakeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.response = self.root / 'response.json'
        self.config = {'source': 'issues', 'items_pointer': '/items',
                       'fields': {'id': '/id', 'title': '/title', 'description': '/body', 'acceptance': '/criteria'}}
        self.items = [{'id': 17, 'title': 'Export', 'body': 'CSV export', 'criteria': ['UTF-8 CSV']}]
        self.write(self.items)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, items):
        self.response.write_text(json.dumps({'items': items}))

    def test_stable_id_and_immutable_snapshot(self):
        first = collect(self.config, self.response)
        path = save(self.root, first)
        self.assertEqual(path, save(self.root, first))
        self.items[0]['body'] = 'CSV export with headers'
        self.write(self.items)
        second = collect(self.config, self.response)
        self.assertEqual(first['requirements'][0]['id'], second['requirements'][0]['id'])
        self.assertNotEqual(path, save(self.root, second))

    def test_projection_duplicate_and_redaction(self):
        self.items[0]['ignored_token'] = 'secret-value'
        self.items[0]['body'] = 'password=secret-value'
        self.write(self.items * 2)
        data = collect(self.config, self.response)
        self.assertEqual(len(data['requirements']), 1)
        self.assertNotIn('secret-value', json.dumps(data))

    def test_conflicting_duplicate_rejected(self):
        other = {**self.items[0], 'title': 'Different'}
        self.write(self.items + [other])
        with self.assertRaisesRegex(ContractError, 'Conflicting'):
            collect(self.config, self.response)

    def test_size_and_missing_field_rejected(self):
        with self.assertRaisesRegex(ContractError, 'max_bytes'):
            collect({**self.config, 'max_bytes': 1}, self.response)
        self.write([{'id': 1}])
        with self.assertRaisesRegex(ContractError, 'Missing mapped'):
            collect(self.config, self.response)

    def test_symlink_escape_rejected(self):
        (self.root / 'inputs').symlink_to(self.root.parent, target_is_directory=True)
        with self.assertRaises(ContractError):
            save(self.root, collect(self.config, self.response))

    def test_https_request_and_auth_not_persisted(self):
        config = {**self.config, 'url': 'https://example.test/issues', 'bearer_token_env': 'TEST_INTAKE_TOKEN'}
        from unittest.mock import MagicMock
        opener = MagicMock()
        opener.open.return_value = io.BytesIO(self.response.read_bytes())
        with patch('sdlc_agent.intake.urllib.request.build_opener', return_value=opener), patch.dict('os.environ', {'TEST_INTAKE_TOKEN': 'abc'}):
            data = collect(config)
        request = opener.open.call_args.args[0]
        self.assertEqual(request.get_header('Authorization'), 'Bearer abc')
        self.assertNotIn('abc', json.dumps(data))
        with self.assertRaises(ContractError):
            NoRedirect().redirect_request(None, None, 302, '', {}, 'https://other.test')

    def test_invalid_url_and_empty_response(self):
        with self.assertRaises(ContractError):
            collect({**self.config, 'url': 'http://example.test'})
        self.write([])
        with self.assertRaises(ContractError):
            collect(self.config, self.response)

    def test_cli_intake_and_workflow_connection(self):
        config_path = self.root / 'source.json'
        config_path.write_text(json.dumps(self.config))
        with patch('sys.stdout', new_callable=io.StringIO) as output:
            self.assertEqual(main(['--repo', str(self.root), 'intake', str(config_path), '--response', str(self.response)]), 0)
            name = json.loads(output.getvalue())['artifact']
        cfg = validate_workflow(default_workflow('Implement export', name))
        for task in cfg['tasks'][:-1]:
            self.assertIn(name, task['required_reads'])


class ContextTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        git(self.root, 'init')
        for name, body in [('core.py', 'VALUE=1'), ('large.log', 'noise' * 2000), ('req.json', '{"goal":"export"}')]:
            (self.root / name).write_text(body)
        git(self.root, 'add', '.')
        self.task = {'id': 'build', 'stage': 'develop', 'prompt': 'Build', 'reads': ['*'], 'writes': ['core.py']}

    def tearDown(self):
        self.tmp.cleanup()

    def test_profile_cli_never_calls_provider(self):
        config_path = self.root / 'workflow.json'
        config_path.write_text(json.dumps(default_workflow('goal')))
        with patch('sdlc_agent.providers.invoke', side_effect=AssertionError('unexpected model call')), patch('sys.stdout', new_callable=io.StringIO) as output:
            self.assertEqual(main(['--repo', str(self.root), 'profile-context', str(config_path), '--task', 'develop']), 0)
        self.assertGreater(json.loads(output.getvalue())['prompt_bytes'], 0)

    def test_source_prefix_stable_across_feedback(self):
        a, am = build(self.root, self.task, {}, 48000)
        b, bm = build(self.root, {**self.task, 'prompt': 'Changed goal'}, {}, 48000, 'retry')
        prefix = am['stable_prefix_bytes']
        self.assertEqual(a.encode()[:prefix], b.encode()[:prefix])
        self.assertEqual(am['stable_prefix_sha256'], bm['stable_prefix_sha256'])
        self.assertNotEqual(a, b)

    def test_exclusion_reduces_bytes_without_truncating_source(self):
        _, before = build(self.root, self.task, {}, 48000)
        prompt, after = build(self.root, {**self.task, 'exclude_reads': ['*.log']}, {}, 48000)
        self.assertLess(after['prompt_bytes'], before['prompt_bytes'])
        self.assertIn('VALUE=1', prompt)
        self.assertNotIn('noisenoise', prompt)

    def test_missing_or_oversized_required_context_blocks(self):
        with self.assertRaisesRegex(ContractError, 'not tracked'):
            build(self.root, {**self.task, 'required_reads': ['missing']}, {}, 48000)
        with self.assertRaisesRegex(ContractError, 'cannot fit'):
            build(self.root, {**self.task, 'required_reads': ['large.log']}, {}, 5000)

    def test_required_file_overrides_exclusions(self):
        prompt, _ = build(self.root, {**self.task, 'reads': [], 'exclude_reads': ['*'], 'required_reads': ['req.json']}, {}, 48000)
        self.assertIn('export', prompt)
        self.assertNotIn('VALUE=1', prompt)

    def test_priority_selects_file_before_budget_fills(self):
        (self.root / 'large.log').write_text('x' * 3000)
        (self.root / 'zzz.py').write_text('important' * 300)
        git(self.root, 'add', '.')
        prompt, _ = build(self.root, {**self.task, 'priority_reads': ['zzz.py']}, {}, 6500)
        payload = json.loads(prompt.split('\nINPUT\n')[1])
        self.assertIn('zzz.py', [item['path'] for item in payload['source']])


class PerformanceTests(unittest.TestCase):
    def test_provider_cache_semantics(self):
        codex = normalize_usage('codex', {'input_tokens': 100, 'cached_input_tokens': 70, 'output_tokens': 20})
        self.assertEqual(codex['uncached_input_tokens'], 30)
        claude = normalize_usage('claude', {'input_tokens': 30, 'cache_read_input_tokens': 70, 'cache_creation_input_tokens': 10})
        self.assertEqual(claude['input_tokens'], 110)
        self.assertIsNone(normalize_usage('codex', {})['cache_read_input_tokens'])
        self.assertIsNone(normalize_usage('codex', {'input_tokens': 1, 'cached_input_tokens': 3})['cache_read_input_tokens'])

    def test_report_distinguishes_result_and_prefill_cache(self):
        report = summarize([{'cache_hit': True, 'prompt_bytes': 400, 'estimated_input_tokens': 100},
                            {'cache_hit': False, 'prompt_bytes': 400, 'normalized_usage': normalize_usage('codex', {'input_tokens': 100, 'cached_input_tokens': 70})}])
        self.assertEqual(report['model_calls'], 1)
        self.assertEqual(report['submitted_prompt_bytes'], 400)
        self.assertEqual(report['estimated_tokens_avoided_by_result_cache'], 100)
        self.assertEqual(report['token_accounting']['cache_read_input_tokens']['reported_total'], 70)
        self.assertIsNone(report['ttft_ms'])

    def test_cache_ttl_and_namespace_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / 'state.db')
            store.cache('key', {'value': 1})
            self.assertIsNone(store.cached('key', 0))
            self.assertEqual(store.cached('key')['value'], 1)
        for value in (-1, True, 99999999):
            with self.assertRaises(ContractError):
                validate_workflow({**default_workflow('goal'), 'cache_ttl_seconds': value})
        with self.assertRaises(ContractError):
            validate_workflow({**default_workflow('goal'), 'cache_namespace': ''})
