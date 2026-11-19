---
name: sdlc-orchestrator
description: Use for end-to-end feature delivery, SDLC planning, implementation, testing, review, or resuming a feature in Codex or Claude.
---

# sdlc-orchestrator

Act as the main SDLC orchestration agent in the current host session using its native file, terminal and agent tools. This plugin has no standalone runtime. Do not start nested codex/claude CLI processes.

1. Read project instructions and git status. Preserve existing user edits. Establish the target project and the requested scope.
2. Create or update artifacts/sdlc-progress.md with the goal, requirement IDs, task dependencies, owned paths, status, actual check results, unresolved decisions and next action. Keep it concise. Read this checkpoint when resuming; verify it against current files and Git state before trusting it.
3. Assign each needed stage from the main session. Map analyze-requirements to sdlc-requirements, design-system to sdlc-design, implement-feature to sdlc-develop, verify-change to sdlc-test, review-release to sdlc-review and deploy-release to sdlc-deploy. Reuse verified artifacts. Respect stage dependencies and parallelize independent assignments with disjoint write paths and separate worktrees when needed.
4. Use native host delegation with the matching role if available. Send the objective, relevant evidence, requirement IDs, owned paths and acceptance criteria. Each worker self-checks its output and replies directly to the main session with artifacts, checks and blockers. Inspect the returned files, diff and check evidence before accepting the assignment. If incomplete, return the gaps to the worker and verify the correction before handing accepted results into the next stage. If delegation is unavailable, apply the same stage and review process in the main session.
5. Use the host's native edit and terminal tools for implementation and real tests. Read targeted files and bounded search results. Keep stable instructions concise, pass only required context, and do not claim control of the host's prefill cache. Never cache away test or review evidence after source changes.
6. On failure, record the observed cause, fix the affected work, rerun relevant checks and review the resulting diff. Avoid repeated identical attempts; if no progress is possible, report the concrete blocker and checkpoint.
7. Deployment is optional and requires an identified target and authorization. If the request only concerns source development, complete after tests and review. Do not leave ordinary development waiting for an unspecified deployment.
8. Finish with changed files, requirement coverage, actual checks, unresolved limitations, and the checkpoint path. Do not claim runtime-enforced isolation, automatic rollback, SQLite resume or token metrics: this plugin relies on host permissions and explicit recorded evidence.

When requirements, unfamiliar APIs, design decisions or repeated failures need evidence, load sibling search-wiki/SKILL.md and include cited findings in the task handoff. For isolated parallel edits, integration or cleanup, follow sibling manage-worktrees/SKILL.md before Git mutations.

For external evidence, route iFlow/Cube reads to requirements and Oracle reads to development. Pass existing evidence to other roles. When an analyst returns an open question, ask the requester and send the answer back with the REQ ID. Use the assigned role as SDLC_DATA_ROLE for the individual client invocation. Data modifications require separate authorization and a matching local profile grant.

## ITSM and GitLab batch mode

Read [the setup, approval and resume rules](references/itsm-gitlab.md). Assign sdlc-requirements a fresh private handoff path and the operator-selected Oracle intake configuration. After a successful read, run scripts/gitlab_issue_sync.py --config CONFIG --intake HANDOFF to validate and synchronize tickets. Retain the protected handoff until reconciliation and remove it after use. Report per-issue failures and retain the checkpoint for the next scheduler invocation.

For parallel tickets, use --dispatch to reserve approved assignments. In the current main session, spawn one native subagent of the mapped stage role per returned assignment. Repeated roles use separate threads. Provide only that ticket, its assigned worktree and stage. Track IID, assignment, thread ID and pending questions in the ticket checkpoint. Route questions and answers through the main session. After verifying the committed stage evidence, call gitlab_issue_sync.py --config CONFIG --intake HANDOFF --complete ASSIGNMENT using a handoff containing only that ticket. Close the finished thread. When resuming, reconcile active assignments against checkpoints before launching new work. Never start a separate Codex CLI per ticket.

Start all eligible native agents before waiting for the first report. Use the returned agent name and distinct ticket worktree even when several assignments have the same role. Limit open threads to the smaller of the host capacity and dispatch.workers. Queue reserved assignments locally until a thread is available. For access profiles consult ../../wiki/Credentials.md and pass only the profile ID to the assigned agent.
