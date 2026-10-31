"""Shared adapter primitives."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import json
import os
import signal
import subprocess
import time
from typing import Any


@dataclass(slots=True)
class NativeRun:
    ok: bool = False
    status: str = "created"
    error_code: str = ""
    message: str = ""
    stdout: str = ""
    stderr: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    duration: float = 0.0


def tail(text: str, limit: int = 8000) -> str:
    return text[-limit:] if len(text) > limit else text


def run_process(
    command: list[str],
    *,
    cwd: Path | None = None,
    timeout: float = 600.0,
    env: dict[str, str] | None = None,
) -> NativeRun:
    started = time.monotonic()
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    try:
        process = subprocess.Popen(
            command,
            cwd=str(cwd) if cwd else None,
            env=merged_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            start_new_session=(os.name != "nt"),
        )
    except FileNotFoundError:
        return NativeRun(ok=False, status="failed", error_code="ENGINE_NOT_FOUND",
                         message=f"executable not found: {command[0]}")
    except OSError as exc:
        return NativeRun(ok=False, status="failed", error_code="ENGINE_NOT_FOUND", message=str(exc))
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        if os.name != "nt" and process.pid:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except OSError:
                process.kill()
        else:
            process.kill()
        stdout, stderr = process.communicate()
        return NativeRun(ok=False, status="timeout", error_code="TIMEOUT",
                         message=f"native run exceeded {timeout:.0f}s",
                         stdout=tail(stdout or ""), stderr=tail(stderr or ""),
                         duration=time.monotonic() - started)
    duration = time.monotonic() - started
    ok = process.returncode == 0
    return NativeRun(ok=ok, status="completed" if ok else "failed",
                     error_code="" if ok else "EVALUATION_FAILED",
                     message="" if ok else f"process exited with {process.returncode}",
                     stdout=tail(stdout or ""), stderr=tail(stderr or ""), duration=duration)


def extract_json(text: str) -> Any | None:
    text = (text or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    while start >= 0:
        depth = 0
        in_string = False
        escaped = False
        for index in range(start, len(text)):
            char = text[index]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:index + 1])
                    except json.JSONDecodeError:
                        break
        start = text.find("{", start + 1)
    return None
