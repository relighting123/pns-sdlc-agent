"""Detached worktrees keep all model writes away from the user's checkout."""
from __future__ import annotations

import fnmatch
import os
from pathlib import Path

from .contracts import ContractError, inside
from .process import run


def git(root: Path, *args: str) -> str:
    result = run(["git", "-c", "core.hooksPath=/dev/null", *args], root, timeout=120, limit=16_000_000)
    if result["code"]:
        raise RuntimeError(result["stderr"] or result["error"] or "git failed")
    return result["stdout"].strip()


def matches(path, patterns):
    return any(fnmatch.fnmatchcase(path, p) for p in patterns)


class Repository:
    def __init__(self, root: Path):
        self.root = Path(git(root, "rev-parse", "--show-toplevel")).resolve()
        self.git_dir = Path(git(self.root, "rev-parse", "--absolute-git-dir"))
        self.state = self.git_dir / "sdlc-agent"
        self.state.mkdir(parents=True, exist_ok=True)

    def clean(self):
        if git(self.root, "status", "--porcelain"):
            raise ContractError("Commit or stash changes before starting a run")

    def add(self, path: Path, head: str):
        path.parent.mkdir(parents=True, exist_ok=True)
        git(self.root, "worktree", "add", "--detach", str(path), head)

    def remove(self, path: Path):
        if path.exists():
            git(self.root, "worktree", "remove", "--force", str(path))

    def publish_ref(self, run_id, head):
        git(self.root, "update-ref", f"refs/heads/sdlc/{run_id}", head)


class RunLock:
    """OS advisory lock: released after a crash, never steal by wall-clock age."""
    def __init__(self, path: Path):
        self.path = path

    def __enter__(self):
        self.file = self.path.open("a+")
        try:
            if os.name == "nt":
                import msvcrt
                self.file.seek(0)
                self.file.write(" ")
                self.file.flush()
                self.file.seek(0)
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.file.close()
            raise ContractError("This run is already active") from None
        return self

    def __exit__(self, *args):
        self.file.close()


def apply_files(root: Path, files: list[dict], patterns: list[str]):
    # Validate the complete set before the first write.
    targets = []
    for f in files:
        if not matches(f["path"], patterns):
            raise ContractError(f"Outside task write scope: {f['path']}")
        targets.append((inside(root, f["path"]), f["content"]))
    for path, content in targets:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def commit(root: Path, task_id: str, paths: list[str]) -> str:
    if paths:
        git(root, "add", "--", *paths)
    git(root, "-c", "user.name=SDLC Agent", "-c", "user.email=sdlc-agent@localhost",
        "commit", "--allow-empty", "-m", f"sdlc: {task_id}")
    return git(root, "rev-parse", "HEAD")
