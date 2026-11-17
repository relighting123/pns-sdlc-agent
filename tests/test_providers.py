import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sdlc_agent.bundle import export
from sdlc_agent.contracts import STAGES
from sdlc_agent.providers import invoke

RESULT = {"status": "completed", "summary": "done", "files": [], "acceptance": ["verified"], "issues": []}


class AdapterTests(unittest.TestCase):
    def test_codex_output_file_and_usage(self):
        def process(argv, cwd, **kwargs):
            self.assertIn("read-only", argv)
            self.assertIn("--ephemeral", argv)
            self.assertEqual(argv[-1], "-")
            self.assertEqual(argv[argv.index("--model") + 1], "stage-model")
            Path(argv[argv.index("--output-last-message") + 1]).write_text(json.dumps(RESULT))
            return {"code": 0, "stdout": json.dumps({"type": "turn.completed", "usage": {"input_tokens": 5}}),
                    "stderr": "", "duration_ms": 10}
        with tempfile.TemporaryDirectory() as temp, patch("sdlc_agent.providers.run", process):
            result, metrics = invoke({"kind": "codex", "model": "default"}, {"model": "stage-model"}, "hello", Path(temp), 1)
        self.assertEqual(result, RESULT)
        self.assertEqual(metrics["usage"]["input_tokens"], 5)

    def test_claude_structured_output_and_disabled_tools(self):
        def process(argv, cwd, **kwargs):
            self.assertEqual(argv[argv.index("--tools") + 1], "")
            self.assertIn("--no-session-persistence", argv)
            return {"code": 0, "stdout": json.dumps({"structured_output": RESULT, "usage": {"input_tokens": 8}}),
                    "stderr": "", "duration_ms": 12}
        with tempfile.TemporaryDirectory() as temp, patch("sdlc_agent.providers.run", process):
            result, metrics = invoke({"kind": "claude"}, {}, "hello", Path(temp), 1)
        self.assertEqual(result, RESULT)
        self.assertEqual(metrics["usage"]["input_tokens"], 8)

    def test_claude_error_envelope(self):
        response = {"code": 0, "stdout": json.dumps({"is_error": True, "result": "quota exceeded"}), "stderr": "", "duration_ms": 1}
        with tempfile.TemporaryDirectory() as temp, patch("sdlc_agent.providers.run", return_value=response):
            with self.assertRaisesRegex(RuntimeError, "quota"):
                invoke({"kind": "claude"}, {}, "hello", Path(temp), 1)

    def test_bundles_have_stage_skills_and_host_manifests(self):
        with tempfile.TemporaryDirectory() as temp:
            for host in ("codex", "claude"):
                root = Path(temp) / host
                report = export(host, root)
                self.assertEqual(report["skills"], 7)
                manifest = json.loads((root / f".{host}-plugin" / "plugin.json").read_text())
                self.assertEqual(manifest["name"], "sdlc-agent")
                self.assertNotIn("mcpServers", manifest)
                self.assertEqual(len(list((root / "skills").glob("*/SKILL.md"))), 7)
                if host == "claude":
                    self.assertEqual(len(list((root / "agents").glob("*.md"))), len(STAGES))
                with self.assertRaises(FileExistsError):
                    export(host, root)


if __name__ == "__main__":
    unittest.main()
