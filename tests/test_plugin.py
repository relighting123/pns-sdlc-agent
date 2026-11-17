import json, pathlib, subprocess, tomllib, unittest
R = pathlib.Path(__file__).resolve().parents[1]
class PluginTests(unittest.TestCase):
    def test_packages_are_complete(self):
        originals = list((R/'skills').glob('*/SKILL.md'))
        self.assertEqual(len(originals), 9)
        for metadata in ('.codex-plugin', '.claude-plugin'):
            manifest=json.loads((R/metadata/'plugin.json').read_text())
            self.assertTrue((R/manifest.get('skills','./skills')).is_dir())
        for registry in ('.agents/plugins/marketplace.json', '.claude-plugin/marketplace.json'):
            entry=json.loads((R/registry).read_text())['plugins'][0]
            source=entry['source']
            path=source['path'] if isinstance(source,dict) else source
            self.assertEqual((R/path).resolve(),R)
        config=json.loads((R/'hooks/hooks.json').read_text())
        self.assertIn('SessionStart',config['hooks'])
        result=subprocess.run(['sh',str(R/'hooks/session-start.sh')],input='{}',text=True,capture_output=True,timeout=3,cwd='/tmp')
        self.assertEqual(result.returncode,0)
        self.assertIn('sdlc-progress.md',result.stdout)
        self.assertFalse((R/'plugins').exists())
    def test_roles(self):
        files=list((R/'.codex/agents').glob('*.toml'))
        self.assertEqual(len(files),6)
        for p in files:
            role=tomllib.loads(p.read_text())
            for key in ('name','description','developer_instructions'):self.assertTrue(role[key])
        self.assertEqual(len(list((R/'agents').glob('*.md'))),6)
    def test_no_runtime(self):
        self.assertFalse((R/'sdlc_agent').exists())
        self.assertFalse((R/'pyproject.toml').exists())
        for p in (R/'skills').rglob('*'):
            if p.is_file():
                for obsolete in ('pip install', 'sdlc-agent run', 'scripts/sdlc.py', 'runtime is optional'):
                    self.assertNotIn(obsolete,p.read_text())
