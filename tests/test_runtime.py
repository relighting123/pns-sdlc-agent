from __future__ import annotations

import copy
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from sdlc_agent import context, providers
from sdlc_agent.cli import default_workflow, main
from sdlc_agent.contracts import ContractError, inside, validate_result, validate_workflow
from sdlc_agent.engine import Engine
from sdlc_agent.process import run
from sdlc_agent.store import Store
from sdlc_agent.workspace import RunLock, apply_files, git


def task(key, stage="develop", deps=(), writes=None, checks=None):
    return {"id": key, "stage": stage, "prompt": f"Implement {key}", "depends_on": list(deps),
            "reads": ["src/*", "artifacts/*", "README.md"],
            "writes": [f"src/{key}.py"] if writes is None else writes, "checks": checks or []}


def config(tasks, **kwargs):
    return {"version": 1, "provider": {"kind": "command", "argv": [sys.executable, "-c", "pass"]},
            "max_attempts": 2, "max_workers": 2, "tasks": tasks, **kwargs}


def result(files=None, status="completed", issues=None):
    return {"status": status, "summary": "Implemented with acceptance evidence", "files": files or [],
            "acceptance": ["REQ-001 covered"], "issues": issues or []}


def fake_provider(conf, current, prompt, cwd, timeout):
    files = [] if not current["writes"] else [{"path": current["writes"][0], "content": "VALUE = 42\n"}]
    return result(files), {"duration_ms": 12, "usage": {"input_tokens": 120, "output_tokens": 30}, "cache_hit": False}


class RepoCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "repo"
        self.root.mkdir()
        git(self.root, "init")
        (self.root / "README.md").write_text("Initial project\n")
        git(self.root, "add", ".")
        git(self.root, "-c", "user.name=Test", "-c", "user.email=test@localhost", "commit", "-m", "initial")
        self.engine = Engine(self.root)
        self.base = git(self.root, "rev-parse", "HEAD")

    def tearDown(self):
        self.temp.cleanup()

    def execute(self, cfg, **kwargs):
        key = self.engine.create(cfg)
        with patch("sdlc_agent.providers.invoke", fake_provider):
            record = self.engine.execute(key, **kwargs)
        return key, record

    def test_parallel_tasks_integrate_and_leave_user_checkout_untouched(self):
        key, record = self.execute(config([task("one"), task("two")]))
        self.assertEqual(record["status"], "succeeded")
        self.assertEqual(git(self.root, "rev-parse", "HEAD"), self.base)
        self.assertFalse((self.root / "src").exists())
        self.assertIn("VALUE = 42", git(self.root, "show", f"sdlc/{key}:src/one.py"))
        self.assertIn("VALUE = 42", git(self.root, "show", f"sdlc/{key}:src/two.py"))
        self.assertEqual(self.engine.report(key)["metrics"]["inference_calls"], 2)

    def test_actual_command_adapter_end_to_end(self):
        script = Path(self.temp.name) / "provider.py"
        script.write_text('''import sys, json
p = json.loads(sys.stdin.read().split("\\nINPUT\\n", 1)[1])
t = p["task"]
files = [{"path": t["writes"][0], "content": "VALUE = 42\\n"}] if t["writes"] else []
print(json.dumps({"status":"completed", "summary":"done", "files":files, "acceptance":["REQ-001"], "issues":[]}))
''')
        cfg = config([task("build"), task("verify", "test", ["build"], [],
                     [[sys.executable, "-c", "from pathlib import Path; assert '42' in Path('src/build.py').read_text()"]]),
                     task("review", "review", ["verify"], [])])
        cfg["provider"]["argv"] = [sys.executable, str(script)]
        key = self.engine.create(cfg)
        record = self.engine.execute(key)
        self.assertEqual(record["status"], "succeeded", record)
        self.assertEqual(len([e for e in self.engine.store.events(key) if e["kind"] == "check"]), 1)

    def test_cli_run_and_report_end_to_end(self):
        cfg = config([task("build")])
        payload = result([{"path": "src/build.py", "content": "VALUE = 42\n"}])
        cfg["provider"]["argv"] = [sys.executable, "-c", "print(" + repr(json.dumps(payload)) + ")"]
        (self.root / "workflow.json").write_text(json.dumps(cfg))
        git(self.root, "add", "workflow.json")
        git(self.root, "-c", "user.name=Test", "-c", "user.email=test@localhost", "commit", "-m", "workflow")
        env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])}
        command = [sys.executable, "-m", "sdlc_agent", "--repo", str(self.root)]
        executed = run(command + ["run", str(self.root / "workflow.json")], self.root, env=env)
        self.assertEqual(executed["code"], 0, executed)
        run_id = json.loads(executed["stdout"])["id"]
        report = run(command + ["report", run_id], self.root, env=env)
        self.assertEqual(report["code"], 0, report)
        self.assertEqual(json.loads(report["stdout"])["metrics"]["inference_calls"], 1)

    def test_test_failure_blocks_review_and_deployment(self):
        cfg = config([task("build"), task("verify", "test", ["build"], [], [[sys.executable, "-c", "raise SystemExit(1)"]]),
                      task("review", "review", ["verify"], []), task("deploy", "deploy", ["review"], [])])
        key, record = self.execute(cfg, allow_deploy=True)
        states = {t["id"]: t["status"] for t in record["tasks"]}
        self.assertEqual(states["verify"], "failed")
        self.assertEqual(states["deploy"], "pending")
        self.assertEqual(states["review"], "pending")
        self.assertEqual(record["status"], "blocked")

    def test_model_cannot_write_outside_scope(self):
        key = self.engine.create(config([task("build")]))
        def malicious(*args):
            return result([{"path": "README.md", "content": "bad"}]), {"duration_ms": 0, "cache_hit": False}
        with patch("sdlc_agent.providers.invoke", malicious):
            record = self.engine.execute(key)
        self.assertEqual(record["tasks"][0]["status"], "failed")
        self.assertEqual(record["head"], self.base)

    def test_direct_provider_mutations_rejected(self):
        key = self.engine.create(config([task("build")]))
        def mutate(conf, task, prompt, cwd, timeout):
            (cwd / "README.md").write_text("bad")
            return fake_provider(conf, task, prompt, cwd, timeout)
        with patch("sdlc_agent.providers.invoke", mutate):
            record = self.engine.execute(key)
        self.assertIn("modified", record["tasks"][0]["error"])

    def test_check_cannot_mutate_source(self):
        key, record = self.execute(config([task("build", checks=[[sys.executable, "-c",
            "from pathlib import Path; Path('src/build.py').write_text('oops')"]])]))
        self.assertEqual(record["tasks"][0]["status"], "failed")
        self.assertIn("mutated", record["tasks"][0]["error"])

    def test_parallel_write_conflicts_are_atomic(self):
        key, record = self.execute(config([task("one", writes=["src/shared.py"]), task("two", writes=["src/shared.py"])]))
        self.assertEqual(record["head"], self.base)
        self.assertTrue(all(t["status"] == "failed" for t in record["tasks"]))

    def test_retry_receives_failure_feedback(self):
        count = 0
        prompts = []
        def flaky(*args):
            nonlocal count
            count += 1
            prompts.append(args[2])
            if count == 1:
                raise ContractError("invalid response format")
            return fake_provider(*args)
        key = self.engine.create(config([task("build")]))
        with patch("sdlc_agent.providers.invoke", flaky):
            record = self.engine.execute(key)
        self.assertEqual(record["status"], "succeeded")
        self.assertIn("invalid response format", prompts[-1])
        self.assertEqual(record["tasks"][0]["attempts"], 2)

    def test_resume_skips_successful_tasks(self):
        cfg = config([task("one"), task("two", deps=["one"])], max_workers=1)
        key = self.engine.create(cfg)
        def blocked(conf, current, *args):
            if current["id"] == "two":
                return result(status="blocked", issues=["Need source"]), {"duration_ms": 0, "cache_hit": False}
            return fake_provider(conf, current, *args)
        with patch("sdlc_agent.providers.invoke", blocked):
            first = self.engine.execute(key)
        self.assertEqual(first["status"], "blocked")
        with patch("sdlc_agent.providers.invoke", side_effect=fake_provider) as invoke:
            final = self.engine.execute(key, retry_failed=True)
        self.assertEqual(final["status"], "succeeded")
        self.assertEqual(invoke.call_count, 1)

    def test_interrupted_task_is_recovered(self):
        key = self.engine.create(config([task("build")]))
        self.engine.store.task(key, "build", "running", attempt=True)
        self.engine.store.status(key, "interrupted")
        with patch("sdlc_agent.providers.invoke", fake_provider):
            self.assertEqual(self.engine.execute(key)["status"], "succeeded")

    def test_context_only_includes_selected_files(self):
        prompt, metrics = context.build(self.root, task("build"), {}, 10000)
        self.assertIn("Initial project", prompt)
        self.assertNotIn("sqlite", prompt)
        self.assertEqual(metrics["source_files"], 1)
        self.assertLessEqual(metrics["prompt_bytes"], 10000)

    def test_context_budget_fails_explicitly(self):
        with self.assertRaises(ContractError):
            context.build(self.root, task("build"), {}, 1)

    def test_cache_reuses_only_matching_inputs(self):
        cfg = config([task("spec", "requirements", writes=["artifacts/spec.md"])])
        self.execute(cfg)
        key = self.engine.create(cfg)
        with patch("sdlc_agent.providers.invoke", side_effect=AssertionError("cache miss")):
            record = self.engine.execute(key)
        self.assertEqual(record["status"], "succeeded")
        self.assertEqual(self.engine.report(key)["metrics"]["cache_hits"], 1)
        cfg["tasks"][0]["prompt"] += " changed"
        other = self.engine.create(cfg)
        with patch("sdlc_agent.providers.invoke", side_effect=fake_provider) as invoke:
            self.engine.execute(other)
        self.assertEqual(invoke.call_count, 1)

    def test_cache_namespace_and_disabled_cache_force_model_call(self):
        cfg = config([task("spec", "requirements", writes=["artifacts/spec.md"])])
        self.execute(cfg)
        for changes in ({"cache_namespace": "v2"}, {"cache": False}, {"cache_ttl_seconds": 0}):
            current = {**cfg, **changes}
            key = self.engine.create(current)
            with patch("sdlc_agent.providers.invoke", side_effect=fake_provider) as invoke:
                record = self.engine.execute(key)
            self.assertEqual(record["status"], "succeeded")
            self.assertEqual(invoke.call_count, 1)
            self.assertEqual(self.engine.report(key)["metrics"]["model_calls"], 1)

    def test_dirty_checkout_rejected(self):
        (self.root / "README.md").write_text("work in progress")
        with self.assertRaises(ContractError):
            self.engine.create(config([task("build")]))

    def test_required_outputs_enforced(self):
        current = task("spec", "requirements", writes=[])
        current["required_outputs"] = ["artifacts/requirements.md"]
        _, record = self.execute(config([current]))
        self.assertIn("required_outputs", record["tasks"][0]["error"])

    def test_total_prompt_budget_is_enforced_before_provider_call(self):
        key = self.engine.create(config([task("build")], max_prompt_bytes=1))
        with patch("sdlc_agent.providers.invoke") as invoke:
            record = self.engine.execute(key)
        invoke.assert_not_called()
        self.assertIn("budget exhausted", record["tasks"][0]["error"])

    def test_repair_invalidates_downstream_and_preserves_original(self):
        cfg = config([task("spec", "requirements", writes=["artifacts/spec.md"]),
                      task("build", deps=["spec"]),
                      task("review", "review", ["build"], [])])
        key = self.engine.create(cfg)
        def failing_review(conf, current, *args):
            if current["stage"] == "review":
                return result(status="blocked", issues=["Fix edge case"]), {"duration_ms": 0, "cache_hit": False}
            return fake_provider(conf, current, *args)
        with patch("sdlc_agent.providers.invoke", failing_review):
            first = self.engine.execute(key)
        repaired = self.engine.repair(key, "build")
        calls = []
        def corrected(conf, current, *args):
            calls.append(current["id"])
            if current["id"] == "build":
                self.assertIn("Fix edge case", current["prompt"])
            return fake_provider(conf, current, *args)
        with patch("sdlc_agent.providers.invoke", corrected):
            final = self.engine.execute(repaired)
        self.assertEqual(final["status"], "succeeded")
        self.assertEqual(calls, ["build", "review"])
        self.assertEqual(self.engine.store.get(key)["status"], "blocked")
        self.assertEqual(first["head"], final["base"])

    def deploy_config(self, health_success=True, rollback_success=True):
        marker = Path(self.temp.name) / "deployed"
        rollback = Path(self.temp.name) / "rolled-back"
        cfg = config([task("build"), task("verify", "test", ["build"], [], [[sys.executable, "-c", "pass"]]),
                      task("review", "review", ["verify"], []), task("deploy", "deploy", ["review"], [])])
        cfg["deployment"] = {
            "command": [sys.executable, "-c", f"from pathlib import Path; Path({str(marker)!r}).write_text('deployed')"],
            "healthcheck": [sys.executable, "-c", "pass" if health_success else "raise SystemExit(1)"],
            "rollback": [sys.executable, "-c", f"from pathlib import Path; Path({str(rollback)!r}).write_text('rolled-back')" if rollback_success else "raise SystemExit(1)"],
        }
        return cfg, marker, rollback

    def test_deployment_waits_then_releases_exact_commit(self):
        cfg, marker, rollback = self.deploy_config()
        key, record = self.execute(cfg)
        self.assertEqual(record["status"], "awaiting_approval")
        self.assertFalse(marker.exists())
        final = self.engine.execute(key, allow_deploy=True)
        self.assertEqual(final["status"], "succeeded")
        self.assertEqual(final["head"], record["head"])
        self.assertTrue(marker.exists())
        self.assertFalse(rollback.exists())
        self.assertTrue(any(e["kind"] == "release_check" for e in self.engine.store.events(key)))

    def test_unhealthy_deployment_rolls_back(self):
        cfg, marker, rollback = self.deploy_config(False)
        key, record = self.execute(cfg, allow_deploy=True)
        self.assertTrue(marker.exists())
        self.assertTrue(rollback.exists())
        self.assertEqual(record["status"], "blocked")
        self.assertEqual(next(t for t in record["tasks"] if t["id"] == "deploy")["status"], "failed")

    def test_failed_rollback_is_indeterminate_and_not_retried(self):
        cfg, _, _ = self.deploy_config(False, False)
        key = self.engine.create(cfg)
        with patch("sdlc_agent.providers.invoke", fake_provider), self.assertRaises(ContractError):
            self.engine.execute(key, allow_deploy=True)
        with self.assertRaisesRegex(ContractError, "unknown"):
            self.engine.execute(key, allow_deploy=True, retry_failed=True)
        self.engine.resolve_deployment(key, "rolled-back")
        self.assertEqual(next(t for t in self.engine.store.get(key)["tasks"] if t["id"] == "deploy")["status"], "failed")

    def test_review_findings_block_release(self):
        cfg, marker, _ = self.deploy_config()
        key = self.engine.create(cfg)
        def review(conf, current, *args):
            if current["stage"] == "review":
                return result(issues=["Incorrect edge case"]), {"duration_ms": 0, "cache_hit": False}
            return fake_provider(conf, current, *args)
        with patch("sdlc_agent.providers.invoke", review):
            record = self.engine.execute(key, allow_deploy=True)
        self.assertEqual(record["status"], "blocked")
        self.assertFalse(marker.exists())


class ContractTests(unittest.TestCase):
    def test_default_workflow_is_valid(self):
        self.assertEqual(len(validate_workflow(default_workflow("Create an API"))["tasks"]), 6)

    def test_cycle_rejected(self):
        with self.assertRaisesRegex(ContractError, "cycle"):
            validate_workflow(config([task("a", deps=["b"]), task("b", deps=["a"])]))

    def test_missing_dependency_rejected(self):
        with self.assertRaisesRegex(ContractError, "Unknown dependency"):
            validate_workflow(config([task("a", deps=["missing"])]))

    def test_shell_string_rejected(self):
        with self.assertRaises(ContractError):
            validate_workflow(config([task("a", checks=["echo hello"])]))

    def test_test_stage_requires_checks(self):
        with self.assertRaises(ContractError):
            validate_workflow(config([task("a", "test")]))

    def test_deployment_requires_test_and_review(self):
        with self.assertRaises(ContractError):
            validate_workflow(config([task("deploy", "deploy", writes=[])]))

    def test_review_cannot_omit_a_development_branch(self):
        with self.assertRaises(ContractError):
            validate_workflow(config([task("a"), task("b"), task("review", "review", ["a"], [])]))

    def test_invalid_paths_rejected(self):
        for path in ("../x", "/tmp/x", ".git/config", ".env", "a/../../x", "a\\b", "C:/x", "AGENTS.md"):
            with self.subTest(path=path), self.assertRaises(ContractError):
                validate_result(result([{"path": path, "content": "x"}]))

    def test_duplicate_artifacts_rejected(self):
        with self.assertRaises(ContractError):
            validate_result(result([{"path": "a", "content": "x"}, {"path": "a", "content": "y"}]))

    def test_non_string_content_rejected(self):
        with self.assertRaises(ContractError):
            validate_result(result([{"path": "a", "content": 1}]))

    def test_secret_redaction(self):
        self.assertNotIn("abc123", context.redact("API_KEY=abc123"))

    def test_symlink_and_partial_write_prevented(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "root"
            root.mkdir()
            (root / "link").symlink_to(Path(temp), target_is_directory=True)
            with self.assertRaises(ContractError):
                apply_files(root, [{"path": "okay", "content": "x"}, {"path": "link/escaped", "content": "x"}], ["*"])
            self.assertFalse((root / "okay").exists())

    def test_process_timeout(self):
        with tempfile.TemporaryDirectory() as root:
            output = run([sys.executable, "-c", "import time; time.sleep(10)"], Path(root), timeout=.1)
            self.assertEqual(output["error"], "timeout")

    def test_output_limit(self):
        with tempfile.TemporaryDirectory() as root:
            output = run([sys.executable, "-c", "print('x'*100000)"], Path(root), limit=1000)
            self.assertEqual(output["error"], "output limit exceeded")

    def test_lock_exclusion_and_release(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "lock"
            with RunLock(path):
                with self.assertRaises(ContractError):
                    with RunLock(path):
                        pass
            with RunLock(path):
                pass

    def test_cache_ttl(self):
        with tempfile.TemporaryDirectory() as root:
            store = Store(Path(root) / "db")
            store.cache("key", {"value": 1})
            self.assertEqual(store.cached("key"), {"value": 1})
            self.assertIsNone(store.cached("key", ttl=-1))

    def test_command_adapter_rejects_malformed_output(self):
        with tempfile.TemporaryDirectory() as root, self.assertRaises(ContractError):
            providers.invoke({"kind": "command", "argv": [sys.executable, "-c", "print('not-json')"]}, {}, "prompt", Path(root), 10)

    def test_cli_init_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as root:
            args = ["--repo", root, "init", "--goal", "Build a calculator"]
            self.assertEqual(main(args), 0)
            self.assertEqual(main(args), 1)

    def test_zero_test_gate(self):
        from sdlc_agent.verify import main as verify
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(verify([root]), 2)


if __name__ == "__main__":
    unittest.main()
