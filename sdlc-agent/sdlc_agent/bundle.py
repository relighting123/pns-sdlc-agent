"""Deterministically export host-specific plugins from the runtime's resources."""
from __future__ import annotations

import json
from pathlib import Path

from . import __version__
from .contracts import STAGES


def export(host: str, destination: Path) -> dict:
    if host not in {"codex", "claude"}:
        raise ValueError("Host must be codex or claude")
    if destination.exists():
        raise FileExistsError(f"Refusing to overwrite {destination}")
    destination.mkdir(parents=True)
    manifest_dir = destination / f".{host}-plugin"
    manifest_dir.mkdir()
    manifest = {"name": "sdlc-agent", "version": __version__,
                "description": "Requirements, design, implementation, verification and deployment workflows",
                "author": {"name": "SDLC Agent contributors"},
                "repository": "https://github.com/relighting123/pns-sdlc-agent", "license": "MIT"}
    if host == "codex":
        manifest["skills"] = "./skills/"
    (manifest_dir / "plugin.json").write_text(json.dumps(manifest, indent=2) + "\n")
    resources = Path(__file__).parent / "resources"
    for stage in STAGES:
        source = resources / "skills" / stage / "SKILL.md"
        body = source.read_text()
        name = body.split("name: ", 1)[1].splitlines()[0]
        target = destination / "skills" / name / "SKILL.md"
        target.parent.mkdir(parents=True)
        target.write_text(body + "\nUse the run-sdlc skill for persisted execution and verification evidence.\n")
        if host == "claude":
            agent = destination / "agents" / f"{stage}.md"
            agent.parent.mkdir(exist_ok=True)
            instructions = body.split("---", 2)[2].strip()
            agent.write_text(f"---\nname: sdlc-{stage}\ndescription: SDLC {stage} specialist. Use for scoped {stage} work.\ntools: Read, Grep, Glob\n---\n\n{instructions}\n\nReturn proposed artifacts; let the SDLC runtime perform writes and checks.\n")
    target = destination / "skills" / "run-sdlc" / "SKILL.md"
    target.parent.mkdir(parents=True)
    target.write_text('''---
name: run-sdlc
description: Execute a complete SDLC workflow with isolated workers, test evidence, resume and deployment gates.
---

# Run SDLC

Use the installed `sdlc-agent` command. Run `sdlc-agent doctor` first.
For a new target project run `sdlc-agent --repo TARGET init --goal "USER REQUIREMENT"`.
Read the generated workflow.json. Set actual source scopes and test commands for the project.
Read only the stage skill needed for the current task; do not preload all stage guidance.
Validate with `sdlc-agent validate TARGET/workflow.json` and commit the workflow in the target repository.
Run `sdlc-agent --repo TARGET run TARGET/workflow.json` and retain the run_id from stderr.
Inspect `sdlc-agent --repo TARGET report RUN_ID` for independently executed checks and usage.
On a blocked run, explain the concrete failure. Use `resume RUN_ID --retry-failed` only after resolving it.
Deployment requires configured command, healthcheck, rollback and user authorization.
When authorized use `sdlc-agent --repo TARGET resume RUN_ID --allow-deploy`.
Never claim deployment from a model summary. Inspect deployment and healthcheck events.
After success the result is on branch `sdlc/RUN_ID`; the user's checked-out branch is unchanged.
Do not call another agent recursively from a runtime worker. The runtime owns scheduling and budgets.
''')
    scripts = destination / "scripts"
    scripts.mkdir()
    (scripts / "sdlc.py").write_text("#!/usr/bin/env python3\nfrom sdlc_agent.cli import main\nraise SystemExit(main())\n")
    return {"host": host, "path": str(destination), "skills": len(STAGES) + 1,
            "native_agents": len(STAGES) if host == "claude" else 0}
