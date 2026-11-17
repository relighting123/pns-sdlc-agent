---
name: run-sdlc
description: Use for end-to-end feature delivery, SDLC planning, implementation, testing, review, or resuming a feature in Codex or Claude.
---

# run-sdlc

Run the workflow in the current host session using its native file, terminal and agent tools. This plugin has no standalone runtime. Do not start nested codex/claude CLI processes.

1. Read project instructions and git status. Preserve existing user edits. Establish the target project and the requested scope.
2. Create or update artifacts/sdlc-progress.md with the goal, requirement IDs, task dependencies, owned paths, status, actual check results, unresolved decisions and next action. Keep it concise. Read this checkpoint when resuming; verify it against current files and Git state before trusting it.
3. Read only the stage skill currently needed from this plugin's sibling skill directories: analyze-requirements, design-system, implement-feature, verify-change, review-release, deploy-release. Follow each in order; reuse existing valid artifacts instead of recreating them.
4. For independent tasks, use the host's native subagent facility only if exposed. Give each worker its objective, relevant paths, acceptance criteria and disjoint write ownership. Pass concise context, not the entire conversation. Do not invent an agent API. If unavailable, execute sequentially. Use separate worktrees when parallel source edits require isolation; inspect and integrate changes explicitly.
5. Use the host's native edit and terminal tools for implementation and real tests. Read targeted files and bounded search results. Keep stable instructions concise, pass only required context, and do not claim control of the host's prefill cache. Never cache away test or review evidence after source changes.
6. On failure, record the observed cause, fix the affected work, rerun relevant checks and review the resulting diff. Avoid repeated identical attempts; if no progress is possible, report the concrete blocker and checkpoint.
7. Deployment is optional and requires an identified target and authorization. If the request only concerns source development, complete after tests and review. Do not leave ordinary development waiting for an unspecified deployment.
8. Finish with changed files, requirement coverage, actual checks, unresolved limitations, and the checkpoint path. Do not claim runtime-enforced isolation, automatic rollback, SQLite resume or token metrics: this plugin relies on host permissions and explicit recorded evidence.

When requirements, unfamiliar APIs, design decisions or repeated failures need evidence, load sibling search-wiki/SKILL.md and include cited findings in the task handoff. For isolated parallel edits, integration or cleanup, follow sibling manage-worktrees/SKILL.md before Git mutations.
