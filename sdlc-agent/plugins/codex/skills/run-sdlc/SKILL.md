---
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
