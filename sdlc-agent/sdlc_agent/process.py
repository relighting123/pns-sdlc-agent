"""Bounded subprocess execution; trusted argv, no implicit shell."""
from __future__ import annotations

import os
import signal
import subprocess
import tempfile
import time
from pathlib import Path


def run(argv: list[str], cwd: Path, *, stdin: str = "", timeout: int = 600,
        limit: int = 4_000_000, env: dict | None = None) -> dict:
    start = time.monotonic()
    with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors, tempfile.TemporaryFile() as source:
        source.write(stdin.encode())
        source.seek(0)
        proc = subprocess.Popen(argv, cwd=cwd, stdin=source, stdout=output, stderr=errors,
                                env=env, start_new_session=os.name != "nt")
        reason = None
        try:
            while proc.poll() is None:
                if time.monotonic() - start > timeout:
                    reason = "timeout"
                    break
                if os.fstat(output.fileno()).st_size + os.fstat(errors.fileno()).st_size > limit:
                    reason = "output limit exceeded"
                    break
                time.sleep(.02)
        finally:
            if proc.poll() is None:
                if os.name == "nt":
                    proc.kill()
                else:
                    os.killpg(proc.pid, signal.SIGKILL)
                proc.wait()
        output.seek(0)
        errors.seek(0)
        stdout, stderr = output.read(limit).decode(errors="replace"), errors.read(limit).decode(errors="replace")
        if os.fstat(output.fileno()).st_size + os.fstat(errors.fileno()).st_size > limit:
            reason = reason or "output limit exceeded"
        return {"argv": argv, "code": proc.returncode if not reason else -1,
                "stdout": stdout, "stderr": stderr, "error": reason,
                "duration_ms": round((time.monotonic() - start) * 1000)}
