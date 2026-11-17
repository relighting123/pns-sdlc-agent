"""Provider adapters create a fresh process/session for every task attempt."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from .contracts import ContractError, RESULT_SCHEMA, validate_result
from .process import run


def invoke(config: dict, task: dict, prompt: str, cwd: Path, timeout: int) -> tuple[dict, dict]:
    kind = config.get("kind", "codex")
    model = task.get("model") or config.get("model")
    with tempfile.TemporaryDirectory(prefix="sdlc-provider-") as temporary:
        tmp = Path(temporary)
        if kind == "codex":
            schema, output = tmp / "schema.json", tmp / "result.json"
            schema.write_text(json.dumps(RESULT_SCHEMA))
            command = ["codex", "exec", "--ephemeral", "--sandbox", "read-only", "--json",
                       "--output-schema", str(schema), "--output-last-message", str(output), "-C", str(cwd)]
            if model:
                command.extend(["--model", model])
            command.append("-")
        elif kind == "claude":
            command = ["claude", "-p", "--output-format", "json", "--tools", "",
                       "--no-session-persistence", "--json-schema", json.dumps(RESULT_SCHEMA)]
            if model:
                command.extend(["--model", model])
        else:
            command = config["argv"]
        response = run(command, cwd, stdin=prompt, timeout=timeout)
        if response["code"]:
            raise RuntimeError(f"Provider failed ({response['code']}): {response['error'] or response['stderr'][-3000:]}")
        usage = {}
        if kind == "codex":
            text = output.read_text() if output.exists() else ""
            for line in response["stdout"].splitlines():
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if event.get("type") == "turn.completed":
                    usage = event.get("usage", {})
        elif kind == "claude":
            envelope = json.loads(response["stdout"])
            if envelope.get("is_error"):
                raise RuntimeError(str(envelope.get("result", "Claude returned an error")))
            usage = envelope.get("usage", {})
            text = envelope.get("structured_output", envelope.get("result", ""))
        else:
            text = response["stdout"]
        try:
            result = validate_result(json.loads(text) if isinstance(text, str) else text)
        except (ValueError, TypeError) as exc:
            raise ContractError(f"Invalid provider result: {exc}") from exc
        return result, {"duration_ms": response["duration_ms"], "usage": usage,
                        "output_bytes": len(json.dumps(result).encode()), "provider": kind,
                        "model": model, "cache_hit": False}
