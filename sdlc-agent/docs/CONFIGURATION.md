# Workflow configuration v1

The workflow is trusted executable configuration. Commit and review it like CI configuration.
The runtime snapshots the complete config at run creation. Resume never silently reloads it.

| Field | Default | Meaning |
|---|---|---|
| `version` | required `1` | Contract version |
| `provider.kind` | `codex` | `codex`, `claude`, or `command` |
| `provider.model` | CLI default | Default inference model, optional |
| `provider.argv` | required for command | Executable and arguments; prompt arrives on stdin |
| `max_workers` | 2 | Concurrent ready tasks, 1–16 |
| `max_attempts` | 2 | Attempts per task per execute/resume, 1–10 |
| `context_bytes` | 48000 | Entire supplied prompt UTF-8 byte limit |
| `max_prompt_bytes` | 2000000 | Run-wide reserved provider prompt bytes, persists across resume |
| `timeout_seconds` | 600 | Per provider/check/deployment command timeout |
| `cache` | true | Cache requirements/design responses for up to 24h |
| `tasks` | required | 1–1000 task objects |
| `deployment` | absent | Trusted command/healthcheck/rollback argv arrays |

Each task has `id`, `stage`, `prompt`, `depends_on`, `reads`, `writes`, `checks`, optional
`required_outputs` and optional `model`. IDs are lowercase letters, numbers, hyphens and underscores;
start with a letter. Stages: requirements, design, develop, test, review, deploy.

`reads` and `writes` use Python `fnmatchcase` against repository-relative POSIX paths. In this matching
model `*` also spans `/`: `src/*` includes nested source files. `required_outputs` lists exact paths
that must be nonempty in the current response. Missing reads are reported as omitted context.
Select all information needed for a task; the runtime does not run semantic retrieval or embeddings.
No file is silently truncated to fit the context. Binary, oversized and symlink sources are omitted.
Protected control paths and `.env*` files are excluded even when matched.

Every test task needs a nonempty checks list. The single final review must depend transitively on
every task other than review/deploy. It is read-only. The single deployment must depend on all other
tasks, including test and review. Requirements/design tasks need not exist in a deliberately narrow
workflow, but `init` generates the complete six-stage flow.

## Provider contract

`command` providers read the supplied prompt from stdin and return exactly one JSON object on stdout.
Send diagnostics to stderr. Do not modify the worktree directly. Exit nonzero for transport failures.
The prompt contains a stable role/skill/schema prefix followed by `INPUT` and a JSON document.

```json
{
  "status": "completed",
  "summary": "Implemented REQ-001; input validation and error handling covered",
  "files": [{"path": "src/service.py", "content": "FULL UTF-8 FILE CONTENT"}],
  "acceptance": ["REQ-001: input is validated before storage"],
  "issues": []
}
```

`status` is `completed` or `blocked`. These five keys are required; additional keys are rejected.
Completed responses need nonempty acceptance evidence. Reviews with issues cannot pass. `files`
contains up to 100 full text replacements, maximum 2 MB each, subject to process output limits.
Artifact deletion is intentionally not part of v1. Update the workflow or add a separately reviewed
migration command when a task needs operations outside this contract.

Codex adapter: `codex exec --ephemeral --sandbox read-only --json --output-schema ...
--output-last-message ... -C WORKTREE -`. Model overrides use `--model`.
Claude adapter: `claude -p --output-format json --tools '' --no-session-persistence --json-schema ...`.
The adapter reads `structured_output` or legacy `result`, checks `is_error`, and records provider usage.
No adapter retries a deployment or shares a prior conversation session.

## Parallel decomposition

To parallelize implementation, replace the generated `develop` task with e.g. `backend` and `frontend`,
both depending on `design`, and set disjoint write scopes (`src/backend/*`, `src/frontend/*`). The test
task depends on both. This creates actual concurrent provider processes; a linear workflow cannot
benefit from increasing max_workers. If both tasks propose the same file, the integration wave fails
atomically; add a dependency to serialize work on that file.

## Budget semantics

Prompt bytes are reserved in a SQLite transaction *before* starting a noncached inference. Reservations
remain even if the provider fails, because consumption may have occurred remotely. A retry uses another
reservation. Cache hits do not reserve provider bytes. This bounds the supplied input, not provider-side
hidden context, tool use, output tokens or monetary cost. Model billing limits should also be configured
at the provider. Reported `estimated_input_tokens` uses bytes/4 and is only a coarse estimate.

## Exit and recovery semantics

`status` and `report` reflect current state and return 2 for incomplete states. A run waiting for deployment
is not successful. `resume --retry-failed` grants another bounded attempt series; there is no unbounded loop.
For substantive code fixes use `repair`, which creates a fresh run with preserved prior evidence and
invalidates descendants. Repair copies failed-task diagnostics into the chosen task's prompt, which is
still subject to the context budget. Very large diagnostics may require concise explicit input/workflow edits.
