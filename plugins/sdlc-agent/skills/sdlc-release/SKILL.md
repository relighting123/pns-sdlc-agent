---
name: sdlc-release
description: Prepare a verified SDLC run for an explicitly requested deployment or rollback using the configured environment commands.
---

Run the bundled `scripts/sdlc.mjs status` for the run, then inspect its verified tree, release plan and recorded checks. For an authorized deployment, use the verified worktree HEAD SHA and invoke `deploy --run <id> --environment <name> --commit <sha>`. Use `commit --run <id> --message <message>` if a commit was requested and the run is still uncommitted. Report the deployment and smoke receipts accurately. Use `rollback` with the same run and environment on explicit request. For an uncertain external operation, inspect the deployment system before suggesting another operation.
