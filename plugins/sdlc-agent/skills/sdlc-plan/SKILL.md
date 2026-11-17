---
name: sdlc-plan
description: Analyze a development request and produce an evidence-backed design, compatibility plan and testable acceptance criteria before editing code.
---

Run the bundled `scripts/sdlc.mjs plan` from the plugin with `--workspace`, a trusted `--config` and `--request-file`. Preserve the returned run ID. Report requirements, open blockers, design trade-offs and verification mapping. Continue an authorized implementation with `resume --run <id>`.
