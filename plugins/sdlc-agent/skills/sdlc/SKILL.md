---
name: sdlc
description: Run evidence-driven software delivery from a scoped change request through requirements, design, code, tests, independent review and release planning.
---

# SDLC delivery

Use the bundled `scripts/sdlc.mjs` entry point relative to this skill's plugin root. Use Node 20 or newer and a Git target checkout. Consult the plugin README only for configuration or diagnostics.

1. Identify the target checkout, user's change request and trusted project command configuration. Use existing CI test, lint and build commands. If missing, inspect CI and propose a configuration with real project commands.
2. Run `node <plugin>/scripts/sdlc.mjs run --workspace <checkout> --config <config> --request-file <request>`. Keep the printed run ID. The worktree starts from committed HEAD.
3. On unclear requirements, report exact blocker questions and call `resume --run <id> --clarification <answer>` with user input. On command or review failure, inspect the saved evidence and continue from the run ID.
4. Return the run ID, worktree path, criteria coverage, exact check outcomes, and remaining release steps. Commit or deploy when the user's request covers the selected action and destination.
