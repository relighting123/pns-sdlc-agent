"""Strict workflow and model-output contracts. No provider SDK dependency."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path, PurePosixPath

STAGES = ("requirements", "design", "develop", "test", "review", "deploy")
ID = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
PROTECTED = {".git", ".sdlc", ".github", ".agents", ".claude", ".codex"}


class ContractError(ValueError):
    pass


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")).encode()).hexdigest()


def relative_path(value: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise ContractError("Expected a nonempty POSIX relative path")
    p = PurePosixPath(value)
    if p.is_absolute() or any(x in ("..", ".") for x in value.split("/")) or ":" in value:
        raise ContractError(f"Unsafe path: {value}")
    if any(x in PROTECTED or x.startswith(".env") for x in p.parts):
        raise ContractError(f"Protected path: {value}")
    if p.name in {"AGENTS.md", "CLAUDE.md", "workflow.json"}:
        raise ContractError(f"Control file is not model-writable: {value}")
    return str(p)


def inside(root: Path, value: str) -> Path:
    relative_path(value)
    p = root / value
    if not p.resolve().is_relative_to(root.resolve()):
        raise ContractError(f"Path escapes workspace: {value}")
    for parent in (p, *p.parents):
        if parent == root:
            break
        if parent.is_symlink():
            raise ContractError(f"Symlink is not writable: {value}")
    return p


def argv(value, label: str):
    if not isinstance(value, list) or not value or not all(isinstance(x, str) and x and "\x00" not in x for x in value):
        raise ContractError(f"{label} must be a nonempty argv array (no shell string)")
    return value


def validate_workflow(config: dict) -> dict:
    if not isinstance(config, dict) or config.get("version") != 1:
        raise ContractError("workflow version must be 1")
    tasks = config.get("tasks", [])
    if not isinstance(tasks, list) or not tasks or len(tasks) > 1000:
        raise ContractError("A workflow requires 1 to 1000 tasks")
    ids = set()
    for task in tasks:
        if not isinstance(task, dict) or not ID.fullmatch(task.get("id", "")):
            raise ContractError("Invalid task id")
        if task["id"] in ids:
            raise ContractError("Duplicate task id")
        ids.add(task["id"])
        if task.get("stage") not in STAGES:
            raise ContractError("Unknown stage")
        if not isinstance(task.get("prompt"), str) or not task["prompt"].strip():
            raise ContractError("Task prompt is required")
        for name in ("depends_on", "reads", "writes", "required_outputs", "required_reads", "priority_reads", "exclude_reads"):
            if not isinstance(task.get(name, []), list) or not all(isinstance(x, str) for x in task.get(name, [])):
                raise ContractError(f"{name} must be a string array")
        for pattern in task.get("reads", []) + task.get("writes", []):
            relative_path(pattern)
        for pattern in task.get("priority_reads", []) + task.get("exclude_reads", []) + task.get("required_reads", []):
            relative_path(pattern)
        if any(any(char in name for char in "*?[") for name in task.get("required_reads", [])):
            raise ContractError("required_reads must contain exact paths")
        for name in task.get("required_outputs", []):
            relative_path(name)
        for command in task.get("checks", []):
            argv(command, "check")
        if task["stage"] == "test" and not task.get("checks"):
            raise ContractError("Test tasks require executable checks")
        if task["stage"] == "deploy" and task.get("writes"):
            raise ContractError("Deploy tasks cannot modify source")
    by_id = {t["id"]: t for t in tasks}
    visited, active = set(), set()
    def visit(key):
        if key in active:
            raise ContractError("Dependency cycle")
        if key in visited:
            return
        if key not in by_id:
            raise ContractError(f"Unknown dependency: {key}")
        active.add(key)
        for dep in by_id[key].get("depends_on", []):
            visit(dep)
        active.remove(key)
        visited.add(key)
    for key in by_id:
        visit(key)
    def ancestors(key):
        deps = set(by_id[key].get("depends_on", []))
        return deps | set().union(*(ancestors(d) for d in deps)) if deps else set()
    for task in tasks:
        if task["stage"] == "deploy":
            deps = ancestors(task["id"])
            stages = {by_id[k]["stage"] for k in deps}
            if not {"test", "review"} <= stages:
                raise ContractError("Deploy requires successful test and review ancestors")
            if not {t["id"] for t in tasks if t["stage"] != "deploy"} <= deps:
                raise ContractError("Deploy must depend on all non-deployment tasks")
        if task["stage"] == "review":
            if task.get("writes"):
                raise ContractError("Review must be read-only")
            implementation = {t["id"] for t in tasks if t["stage"] not in {"review", "deploy"}}
            if not implementation <= ancestors(task["id"]):
                raise ContractError("Review must depend on all pre-release tasks")
    if sum(t["stage"] == "deploy" for t in tasks) > 1:
        raise ContractError("Use one deployment task per run")
    if sum(t["stage"] == "review" for t in tasks) > 1:
        raise ContractError("Use one final review task per run")
    provider = config.get("provider", {"kind": "codex"})
    if provider.get("kind") not in {"codex", "claude", "command"}:
        raise ContractError("Provider kind must be codex, claude, or command")
    if provider.get("kind") == "command":
        argv(provider.get("argv"), "provider.argv")
    for name, default, upper in (("max_workers", 2, 16), ("max_attempts", 2, 10),
                                  ("context_bytes", 48000, 2000000),
                                  ("max_prompt_bytes", 2000000, 1000000000),
                                  ("timeout_seconds", 600, 86400)):
        value = config.get(name, default)
        if type(value) is not int or value < 1 or value > upper:
            raise ContractError(f"Invalid {name}")
    ttl = config.get("cache_ttl_seconds", 86400)
    if type(ttl) is not int or not 0 <= ttl <= 2592000:
        raise ContractError("cache_ttl_seconds must be 0..2592000")
    if not isinstance(config.get("cache_namespace", "default"), str) or not config.get("cache_namespace", "default"):
        raise ContractError("cache_namespace must be a nonempty string")
    if type(config.get("cache", True)) is not bool:
        raise ContractError("cache must be boolean")
    deploy = config.get("deployment")
    if deploy:
        for key in ("command", "healthcheck", "rollback"):
            argv(deploy.get(key), f"deployment.{key}")
    return config


RESULT_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["status", "summary", "files", "acceptance", "issues"],
    "properties": {
        "status": {"type": "string", "enum": ["completed", "blocked"]},
        "summary": {"type": "string"},
        "files": {"type": "array", "items": {"type": "object", "additionalProperties": False,
            "required": ["path", "content"], "properties": {
                "path": {"type": "string"}, "content": {"type": "string"}}}},
        "acceptance": {"type": "array", "items": {"type": "string"}},
        "issues": {"type": "array", "items": {"type": "string"}},
    },
}


def validate_result(result: dict) -> dict:
    if not isinstance(result, dict) or set(result) != set(RESULT_SCHEMA["required"]):
        raise ContractError("Result must contain exactly status, summary, files, acceptance, issues")
    if result["status"] not in ("completed", "blocked"):
        raise ContractError("Invalid result status")
    if not isinstance(result["summary"], str) or not result["summary"].strip():
        raise ContractError("Nonempty summary required")
    for key in ("acceptance", "issues"):
        if not isinstance(result[key], list) or not all(isinstance(x, str) for x in result[key]):
            raise ContractError(f"Invalid {key}")
    if not isinstance(result["files"], list) or len(result["files"]) > 100:
        raise ContractError("files must contain at most 100 entries")
    seen = set()
    for f in result["files"]:
        if not isinstance(f, dict) or set(f) != {"path", "content"} or not isinstance(f["content"], str):
            raise ContractError("Invalid file entry")
        relative_path(f["path"])
        if f["path"] in seen or len(f["content"].encode()) > 2_000_000:
            raise ContractError("Duplicate or oversized file")
        seen.add(f["path"])
    return result
