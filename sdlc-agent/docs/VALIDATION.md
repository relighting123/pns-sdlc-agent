# Validation record

Implementation date: 2026-11-17. Python runtime: 3.12.14, Linux.

## Executed validation

Local result: **45 tests passed** (`python3 -m unittest discover -s tests -v`, 15.637 seconds).

The initial GitHub matrix exposed a Python 3.11 discovery-root leak from the shared unittest loader.
The gate now creates a fresh TestLoader for each invocation; the zero-test regression case covers it.
Python 3.12 and 3.13 passed the initial remote test/build matrix. See the PR checks for the final matrix.

- Standard-library unit and integration suite: contracts, DAG cycles, command argv, artifact scope,
  symlink protection, process timeout/output cap, SQLite cache, lock exclusion, total prompt budget,
  actual Git worktree integration, parallel conflicts, retry feedback, resume, repair invalidation,
  test failure blocking, review blocking, deployment authorization, exact-commit release checks,
  healthcheck failure, rollback and indeterminate-deployment reconciliation.
- Real command-provider subprocess end-to-end: stdin prompt → structured JSON → proposed source →
  actual check command → read-only review → Git result branch.
- Codex and Claude adapter contract tests: command flags, model override, output parsing, usage and errors.
- Plugin generation: correct host manifest locations, seven skills, six Claude role files, no MCP dependency,
  and refusal to overwrite an existing plugin directory.
- Python wheel build and package-resource inspection; CLI/module entrypoints.

The test suite uses controlled inference responses to deterministically exercise failure paths. These
tests validate orchestration and contracts, not the semantic coding ability of an LLM.

## Live provider status

Codex authentication status was present. A real `codex exec` smoke attempt failed before inference because
the environment's Codex state directory was read-only (`failed to initialize ... Read-only file system`).
This was not treated as a model success. No credential relocation or sandbox bypass was attempted.

Claude Code was not installed in the execution environment. Its adapter was contract-tested with
representative JSON envelopes but not live authenticated inference. The native host plugin loading
commands were not run here. Validate them against the host versions used by your team.

## Deployment status

Tests executed real local commands for release, health verification and rollback in temporary directories.
No production account, cloud environment or user service was deployed. Configure the target project's
trusted deployment commands and validate them in staging before production use.

## Scope of CI

The added GitHub Actions workflow runs the standalone Python package tests and builds a wheel on Linux
with Python 3.11, 3.12 and 3.13. The existing upstream TypeScript/Rust tree is not changed by this runtime
and its full build/test suite was not run for these Python additions. Remote CI status must be checked
after push; local passing tests are not proof of a completed GitHub Actions run.
