"""DAG scheduler with durable checkpoints and evidence-gated deployment."""
from __future__ import annotations

import concurrent.futures
import json
import os
import time
import uuid
from pathlib import Path

from . import context, providers
from .contracts import ContractError, digest, validate_workflow
from .process import run
from .store import Store
from .workspace import Repository, RunLock, apply_files, commit, git


class Engine:
    def __init__(self, root: Path):
        self.repo = Repository(root)
        self.store = Store(self.repo.state / "state.sqlite3")

    def create(self, config: dict) -> str:
        validate_workflow(config)
        self.repo.clean()
        run_id = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:8]
        base = git(self.repo.root, "rev-parse", "HEAD")
        self.store.create(run_id, config, base)
        self.store.event(run_id, None, "created", {"base": base, "config_digest": digest(config)})
        return run_id

    def repair(self, run_id: str, task_id: str, feedback: str = "") -> str:
        """Fork a bounded correction run; retain unaffected checkpoints and audit history."""
        with RunLock(self.repo.state / f"{run_id}.lock"):
            record = self.store.get(run_id)
            if record["status"] in {"running", "succeeded"} or any(t["status"] == "deploying" for t in record["tasks"]):
                raise ContractError("Repair requires a stopped, incomplete run with no indeterminate deployment")
            config = json.loads(json.dumps(record["config"]))
            current = next((t for t in config["tasks"] if t["id"] == task_id), None)
            if not current or current["stage"] in {"review", "deploy"}:
                raise ContractError("Choose a requirements, design, develop or test task to repair")
            diagnostics = [{"task": t["id"], "error": t["error"], "result": t["result"]}
                           for t in record["tasks"] if t["status"] in {"failed", "blocked"}]
            if not feedback and not diagnostics:
                raise ContractError("Provide feedback or repair a run with recorded failures")
            current["prompt"] += "\nCORRECTION REQUEST\n" + context.redact(feedback) + "\n" + json.dumps(diagnostics)
            affected = {task_id}
            while True:
                previous = set(affected)
                affected |= {t["id"] for t in config["tasks"] if affected.intersection(t.get("depends_on", []))}
                if previous == affected:
                    break
            validate_workflow(config)
            new_id = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:8]
            self.store.create(new_id, config, record["head"])
            retained = [(t["id"], t["result"]) for t in record["tasks"] if t["id"] not in affected and t["status"] == "succeeded"]
            self.store.checkpoint(new_id, record["head"], retained)
            self.store.event(new_id, task_id, "repair_created", {"parent_run": run_id, "invalidated": sorted(affected)})
            return new_id

    def execute(self, run_id: str, *, allow_deploy=False, retry_failed=False) -> dict:
        record = self.store.get(run_id)
        with RunLock(self.repo.state / f"{run_id}.lock"):
            if any(t["status"] == "deploying" for t in record["tasks"]):
                raise ContractError("Deployment outcome unknown after interruption; use resolve-deployment after inspecting the target")
            if record["status"] == "succeeded":
                return record
            # A run's config/base are immutable. Only interrupted/explicitly retried tasks reset.
            for task in record["tasks"]:
                if task["status"] == "running" or (retry_failed and task["status"] in {"failed", "blocked"}):
                    self.store.task(run_id, task["id"], "pending")
            self.store.status(run_id, "running")
            integration = self.repo.state / "worktrees" / run_id / "integration"
            self.repo.remove(integration)
            self.repo.add(integration, record["head"])
            try:
                return self._schedule(run_id, integration, allow_deploy)
            except BaseException as exc:
                self.store.status(run_id, "interrupted" if isinstance(exc, KeyboardInterrupt) else "failed")
                self.store.event(run_id, None, "runtime_error", {"message": context.redact(str(exc))})
                raise
            finally:
                self.repo.remove(integration)

    def _schedule(self, run_id, integration, allow_deploy):
        while True:
            record = self.store.get(run_id)
            config = record["config"]
            states = {t["id"]: t for t in record["tasks"]}
            if all(t["status"] == "succeeded" for t in states.values()):
                self.repo.publish_ref(run_id, record["head"])
                self.store.status(run_id, "succeeded")
                return self.store.get(run_id)
            ready = [t for t in config["tasks"] if states[t["id"]]["status"] in {"pending", "awaiting_approval"}
                     and all(states[d]["status"] == "succeeded" for d in t.get("depends_on", []))]
            if not ready:
                self.store.status(run_id, "blocked")
                self.repo.publish_ref(run_id, record["head"])
                return self.store.get(run_id)
            deploy_tasks = [t for t in ready if t["stage"] == "deploy"]
            normal = [t for t in ready if t["stage"] != "deploy"]
            if not normal and deploy_tasks:
                task = deploy_tasks[0]
                if not allow_deploy:
                    self.store.task(run_id, task["id"], "awaiting_approval")
                    self.store.status(run_id, "awaiting_approval")
                    self.repo.publish_ref(run_id, record["head"])
                    return self.store.get(run_id)
                self._deploy(run_id, task, integration, record)
                continue
            batch = normal[:config.get("max_workers", 2)]
            completed = []
            with concurrent.futures.ThreadPoolExecutor(max_workers=len(batch)) as pool:
                futures = {pool.submit(self._worker, run_id, task, record): task for task in batch}
                for future in concurrent.futures.as_completed(futures):
                    task = futures[future]
                    try:
                        outcome = future.result()
                    except Exception as exc:
                        self.store.task(run_id, task["id"], "failed", error=context.redact(str(exc)))
                        continue
                    if outcome:
                        completed.append((task, outcome))
            # Integrate a whole wave atomically with respect to the durable checkpoint.
            prior = record["head"]
            paths = set()
            merged = []
            try:
                for task, outcome in sorted(completed, key=lambda item: item[0]["id"]):
                    changed = {f["path"] for f in outcome["result"]["files"]}
                    if paths & changed:
                        raise ContractError(f"Parallel write conflict: {sorted(paths & changed)}; serialize these tasks")
                    paths |= changed
                    git(integration, "-c", "user.name=SDLC Agent", "-c", "user.email=sdlc-agent@localhost",
                        "cherry-pick", "--allow-empty", outcome["commit"])
                    merged.append((task["id"], outcome["result"]))
                # Combined changes must pass all checks from this wave too.
                for task, _ in completed:
                    self._checks(run_id, task, integration, config, kind="integration_check")
                head = git(integration, "rev-parse", "HEAD")
                self.store.checkpoint(run_id, head, merged)
                self.repo.publish_ref(run_id, head)
            except Exception as exc:
                try:
                    git(integration, "cherry-pick", "--abort")
                except RuntimeError:
                    pass
                git(integration, "reset", "--hard", prior)
                for task, _ in completed:
                    self.store.task(run_id, task["id"], "failed", error=context.redact(str(exc)))
            finally:
                for task, _ in completed:
                    self.repo.remove(self.repo.state / "worktrees" / run_id / task["id"])

    def _worker(self, run_id, task, record):
        config = record["config"]
        path = self.repo.state / "worktrees" / run_id / task["id"]
        dependencies = {t["id"]: {"summary": t["result"]["summary"],
                                    "acceptance": t["result"]["acceptance"],
                                    "files": [f["path"] for f in t["result"]["files"]]}
                        for t in record["tasks"] if t["id"] in task.get("depends_on", [])}
        feedback = ""
        for attempt in range(config.get("max_attempts", 2)):
            self.repo.remove(path)
            self.repo.add(path, record["head"])
            self.store.task(run_id, task["id"], "running", attempt=True)
            try:
                prompt, metrics = context.build(path, task, dependencies, config.get("context_bytes", 48000), feedback)
                provider = config.get("provider", {"kind": "codex"})
                cache_key = digest({"prompt": prompt, "provider": provider, "head": record["head"], "contract": 1})
                cacheable = task["stage"] in {"requirements", "design"} and config.get("cache", True)
                result = self.store.cached(cache_key) if cacheable else None
                if result:
                    metrics.update({"cache_hit": True, "duration_ms": 0, "usage": {}})
                else:
                    self.store.reserve(run_id, metrics["prompt_bytes"], config.get("max_prompt_bytes", 2000000))
                    result, measured = providers.invoke(provider, task, prompt, path, config.get("timeout_seconds", 600))
                    metrics.update(measured)
                self.store.event(run_id, task["id"], "inference", metrics)
                # Providers propose artifacts; direct edits violate the adapter contract.
                if git(path, "status", "--porcelain"):
                    raise ContractError("Provider modified the worktree directly; return files in JSON instead")
                if result["status"] == "blocked":
                    self.store.task(run_id, task["id"], "blocked", result=result, error="; ".join(result["issues"]))
                    self.repo.remove(path)
                    return None
                if not result["acceptance"]:
                    raise ContractError("Completed result requires acceptance evidence")
                if task["stage"] == "review" and result["issues"]:
                    raise ContractError("Review has unresolved issues")
                outputs = {f["path"] for f in result["files"] if f["content"].strip()}
                if not set(task.get("required_outputs", [])) <= outputs:
                    raise ContractError("Missing nonempty required_outputs in agent result")
                apply_files(path, result["files"], task.get("writes", []))
                paths = [f["path"] for f in result["files"]]
                if paths:
                    git(path, "add", "--", *paths)
                self._checks(run_id, task, path, config)
                sha = commit(path, task["id"], paths)
                if cacheable:
                    self.store.cache(cache_key, result)
                return {"commit": sha, "result": result}
            except Exception as exc:
                feedback = context.redact(str(exc))[-4000:]
                self.store.event(run_id, task["id"], "attempt_failed", {"attempt": attempt + 1, "error": feedback})
                if attempt + 1 == config.get("max_attempts", 2):
                    self.store.task(run_id, task["id"], "failed", error=feedback)
                    self.repo.remove(path)
                    return None
        return None

    def _checks(self, run_id, task, path, config, kind="check"):
        for command in task.get("checks", []):
            before = git(path, "diff", "HEAD", "--binary")
            result = run(command, path, timeout=config.get("timeout_seconds", 600))
            evidence = {**result, "stdout": context.redact(result["stdout"])[-8000:],
                        "stderr": context.redact(result["stderr"])[-8000:]}
            self.store.event(run_id, task["id"], kind, evidence)
            if result["code"]:
                raise ContractError(f"Check failed: {command!r}\n{evidence['stdout']}\n{evidence['stderr']}\n{result['error'] or ''}")
            if git(path, "diff", "HEAD", "--binary") != before:
                raise ContractError("Check mutated tracked source; checks must not rewrite artifacts")

    def _deploy(self, run_id, task, path, record):
        config = record["config"]
        deployment = config.get("deployment")
        if not deployment:
            self.store.task(run_id, task["id"], "blocked", error="Configure deployment command, healthcheck, and rollback")
            return
        # Re-run tests on the exact commit about to be deployed.
        for item in config["tasks"]:
            if item["stage"] == "test":
                self._checks(run_id, item, path, config, "release_check")
        approval = {"head": record["head"], "config_digest": digest(config)}
        self.store.event(run_id, task["id"], "deployment_authorized", approval)
        self.store.task(run_id, task["id"], "deploying", attempt=True)
        deployment_env = {**os.environ, "SDLC_COMMIT": record["head"], "SDLC_RUN_ID": run_id,
                          "SDLC_CONFIG_DIGEST": digest(config)}
        try:
            for key in ("command", "healthcheck"):
                result = run(deployment[key], path, timeout=config.get("timeout_seconds", 600), env=deployment_env)
                self.store.event(run_id, task["id"], f"deployment_{key}", self._safe_log(result))
                if result["code"]:
                    raise RuntimeError(f"Deployment {key} failed")
                if git(path, "diff", "HEAD", "--binary"):
                    raise RuntimeError("Deployment modified tracked source")
        except Exception as exc:
            try:
                rollback = run(deployment["rollback"], path, timeout=config.get("timeout_seconds", 600), env=deployment_env)
                self.store.event(run_id, task["id"], "deployment_rollback", self._safe_log(rollback))
                if rollback["code"]:
                    raise RuntimeError("Rollback failed; target requires manual reconciliation")
            except Exception as rollback_error:
                self.store.event(run_id, task["id"], "deployment_uncertain", {"error": str(rollback_error)})
                # Retain deploying: automatic retry must never duplicate unknown side effects.
                raise ContractError(str(rollback_error)) from rollback_error
            self.store.task(run_id, task["id"], "failed", error=str(exc))
            return
        result = {"status": "completed", "summary": "Deployment and health check passed", "files": [],
                  "acceptance": [f"Deployed commit {record['head']}", "Health check exited 0"], "issues": []}
        self.store.checkpoint(run_id, record["head"], [(task["id"], result)])

    @staticmethod
    def _safe_log(result):
        return {**result, "stdout": context.redact(result["stdout"])[-8000:],
                "stderr": context.redact(result["stderr"])[-8000:]}

    def resolve_deployment(self, run_id, outcome):
        with RunLock(self.repo.state / f"{run_id}.lock"):
            record = self.store.get(run_id)
            tasks = [t for t in record["tasks"] if t["status"] == "deploying"]
            if len(tasks) != 1:
                raise ContractError("No single indeterminate deployment to resolve")
            task = tasks[0]
            if outcome == "rolled-back":
                self.store.task(run_id, task["id"], "failed", error="Operator confirmed rollback")
            elif outcome == "succeeded":
                path = self.repo.state / "worktrees" / run_id / "reconcile"
                self.repo.remove(path)
                self.repo.add(path, record["head"])
                try:
                    result = run(record["config"]["deployment"]["healthcheck"], path,
                                 timeout=record["config"].get("timeout_seconds", 600),
                                 env={**os.environ, "SDLC_COMMIT": record["head"], "SDLC_RUN_ID": run_id,
                                      "SDLC_CONFIG_DIGEST": digest(record["config"])})
                    self.store.event(run_id, task["id"], "reconcile_healthcheck", self._safe_log(result))
                    if result["code"]:
                        raise ContractError("Health check failed; deployment remains indeterminate")
                    self.store.checkpoint(run_id, record["head"], [(task["id"], {
                        "status": "completed", "summary": "Operator reconciled deployment; health check passed",
                        "files": [], "acceptance": [record["head"]], "issues": []})])
                finally:
                    self.repo.remove(path)
            else:
                raise ContractError("Invalid reconciliation outcome")
            self.store.event(run_id, task["id"], "operator_reconciliation", {"outcome": outcome})
            self.store.status(run_id, "pending")

    def report(self, run_id):
        record = self.store.get(run_id)
        events = self.store.events(run_id)
        calls = [e["payload"] for e in events if e["kind"] == "inference"]
        durations = sorted(c["duration_ms"] for c in calls if not c["cache_hit"])
        return {"id": run_id, "status": record["status"], "base": record["base"], "head": record["head"],
                "branch": f"sdlc/{run_id}", "tasks": [{k: t[k] for k in ("id", "status", "attempts", "error")} for t in record["tasks"]],
                "metrics": {"inference_calls": len(calls), "cache_hits": sum(c["cache_hit"] for c in calls),
                            "reserved_prompt_bytes": self.store.reserved(run_id),
                            "prompt_bytes": sum(c["prompt_bytes"] for c in calls),
                            "estimated_input_tokens": sum(c["estimated_input_tokens"] for c in calls),
                            "provider_usage": [c.get("usage", {}) for c in calls],
                            "latency_p50_ms": durations[len(durations)//2] if durations else None,
                            "latency_p95_ms": durations[min(len(durations)-1, int(len(durations)*.95))] if durations else None},
                "events": events}
