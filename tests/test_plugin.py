import json, pathlib, subprocess, tomllib, unittest
R = pathlib.Path(__file__).resolve().parents[1]
class PluginTests(unittest.TestCase):
    def test_packages_are_complete(self):
        originals = list((R/'skills').glob('*/SKILL.md'))
        self.assertEqual(len(originals), 7)
        for host in ('codex','claude'):
            root=R/'plugins'/host
            manifest=json.loads((root/('.codex-plugin' if host=='codex' else '.claude-plugin')/'plugin.json').read_text())
            self.assertTrue((root/manifest.get('skills', './skills')).is_dir())
            for p in originals:
                self.assertEqual(p.read_bytes(),(root/'skills'/p.parent.name/p.name).read_bytes())
            config=json.loads((root/'hooks/hooks.json').read_text())
            self.assertIn('SessionStart',config['hooks'])
            result=subprocess.run(['sh',str(root/'hooks/session-start.sh')],input='{}',text=True,capture_output=True,timeout=3,cwd='/tmp')
            self.assertEqual(result.returncode,0)
            self.assertIn('sdlc-progress.md',result.stdout)
    def test_roles(self):
        files=list((R/'adapters/codex/agents').glob('*.toml'))
        self.assertEqual(len(files),6)
        for p in files:
            role=tomllib.loads(p.read_text())
            for key in ('name','description','developer_instructions'):self.assertTrue(role[key])
        self.assertEqual(len(list((R/'plugins/claude/agents').glob('*.md'))),6)
    def test_no_runtime(self):
        self.assertFalse((R/'sdlc_agent').exists())
        self.assertFalse((R/'pyproject.toml').exists())
        for p in (R/'plugins').rglob('*'):
            if p.is_file():
                for obsolete in ('pip install', 'sdlc-agent run', 'scripts/sdlc.py', 'runtime is optional'):
                    self.assertNotIn(obsolete,p.read_text())
