"""
Builtin shell/process tools for Aries.
"""

from __future__ import annotations

import itertools
import json
import os
import subprocess
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from aries.config import DesktopOpsProcessPollConfig
from aries.core.workspace import resolve_and_validate_path
from aries.exceptions import FileToolError
from aries.tools.base import BaseTool, ToolResult


def _now_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"


def _json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _merge_env(env: dict[str, str] | None) -> dict[str, str]:
    merged = {str(k): str(v) for k, v in os.environ.items()}
    if env:
        merged.update({str(k): str(v) for k, v in env.items()})
    return merged


def _normalize_argv(argv: list[str]) -> list[str]:
    return [str(part) for part in argv]


def _resolve_cwd(
    cwd: str | None,
    *,
    workspace: Any | None,
    allowed_paths: list[Path] | None,
    denied_paths: list[Path] | None,
) -> Path:
    if cwd is None:
        if workspace is not None:
            return resolve_and_validate_path(
                ".",
                workspace=workspace,
                allowed_paths=allowed_paths,
                denied_paths=denied_paths,
            )
        return Path.cwd().expanduser().resolve()
    return resolve_and_validate_path(
        cwd,
        workspace=workspace,
        allowed_paths=allowed_paths,
        denied_paths=denied_paths,
    )


def _truncate_tail(buffer: bytes, chunk: bytes, max_bytes: int) -> bytes:
    if not chunk:
        return buffer
    combined = buffer + chunk
    if len(combined) <= max_bytes:
        return combined
    return combined[-max_bytes:]


@dataclass
class _ProcessState:
    process: subprocess.Popen[bytes]
    argv: list[str]
    cwd: str
    started_at: str
    max_bytes: int
    stdout_tail: bytes = b""
    stderr_tail: bytes = b""
    bytes_stdout_total: int = 0
    bytes_stderr_total: int = 0
    last_output_at: datetime | None = None
    lock: threading.Lock = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.lock = threading.Lock()


_PROCESS_TABLE: dict[str, _ProcessState] = {}
_PROCESS_LOCK = threading.Lock()
_PROCESS_COUNTER = itertools.count(1)


def _next_process_id() -> str:
    return f"process-{next(_PROCESS_COUNTER)}"


def _start_reader(state: _ProcessState, stream_name: Literal["stdout", "stderr"]) -> None:
    stream = getattr(state.process, stream_name)
    if stream is None:
        return

    def _read_loop() -> None:
        while True:
            try:
                reader = getattr(stream, "read1", None)
                if reader is None:
                    chunk = stream.read(4096)
                else:
                    chunk = reader(4096)
            except Exception:
                break
            if not chunk:
                break
            with state.lock:
                if stream_name == "stdout":
                    state.bytes_stdout_total += len(chunk)
                    state.stdout_tail = _truncate_tail(
                        state.stdout_tail, chunk, state.max_bytes
                    )
                else:
                    state.bytes_stderr_total += len(chunk)
                    state.stderr_tail = _truncate_tail(
                        state.stderr_tail, chunk, state.max_bytes
                    )
                state.last_output_at = datetime.utcnow()

    thread = threading.Thread(target=_read_loop, daemon=True)
    thread.start()


def _get_process(process_id: str) -> _ProcessState | None:
    with _PROCESS_LOCK:
        return _PROCESS_TABLE.get(process_id)


def _set_process(process_id: str, state: _ProcessState) -> None:
    with _PROCESS_LOCK:
        _PROCESS_TABLE[process_id] = state


class BuiltinShellStartTool(BaseTool):
    name = "start"
    description = "Start a process and return a handle for polling."
    server_id = "shell"
    risk_level = "exec"
    requires_shell = True
    mutates_state = True
    emits_artifacts = False
    path_params = ("cwd",)
    path_params_optional = True
    uses_filesystem_paths = True

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "argv": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Command argv list",
                },
                "cwd": {"type": "string", "description": "Working directory"},
                "env": {
                    "type": "object",
                    "additionalProperties": {"type": "string"},
                    "description": "Environment variables to merge",
                },
                "timeout_seconds": {
                    "type": "integer",
                    "description": "Startup timeout in seconds",
                    "minimum": 1,
                },
            },
            "required": ["argv"],
        }

    async def execute(
        self,
        argv: list[str],
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        timeout_seconds: int | None = None,
        **kwargs: Any,
    ) -> ToolResult:
        if not isinstance(argv, list) or not argv:
            return ToolResult(False, "", error="argv must be a non-empty list of strings")
        try:
            resolved_cwd = _resolve_cwd(
                cwd,
                workspace=kwargs.get("workspace"),
                allowed_paths=kwargs.get("allowed_paths"),
                denied_paths=kwargs.get("denied_paths"),
            )
        except FileToolError as exc:
            return ToolResult(False, "", error=str(exc))

        poll_cfg = kwargs.get("process_poll") or DesktopOpsProcessPollConfig()
        argv_list = _normalize_argv(argv)
        started_at = _now_iso()
        process_id = _next_process_id()
        try:
            process = subprocess.Popen(
                argv_list,
                cwd=str(resolved_cwd),
                env=_merge_env(env),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except Exception as exc:
            payload = {
                "status": "error",
                "data": None,
                "meta": {},
                "error": {"type": "StartFailed", "message": str(exc)},
            }
            return ToolResult(False, _json(payload), error=str(exc))

        state = _ProcessState(
            process=process,
            argv=argv_list,
            cwd=str(resolved_cwd),
            started_at=started_at,
            max_bytes=int(getattr(poll_cfg, "max_bytes", 4000)),
            last_output_at=datetime.utcnow(),
        )
        _set_process(process_id, state)
        _start_reader(state, "stdout")
        _start_reader(state, "stderr")

        if timeout_seconds:
            try:
                process.wait(timeout=float(timeout_seconds))
            except subprocess.TimeoutExpired:
                pass

        payload = {
            "status": "ok",
            "data": {
                "process_id": process_id,
                "pid": int(process.pid),
                "argv": argv_list,
                "cwd": str(resolved_cwd),
                "started_at": started_at,
            },
            "meta": {},
        }
        return ToolResult(
            True,
            _json(payload),
            metadata={"process_id": process_id, "cwd": str(resolved_cwd)},
        )


class BuiltinShellPollTool(BaseTool):
    name = "poll"
    description = "Poll a running process for output."
    server_id = "shell"
    risk_level = "read"
    requires_shell = True
    mutates_state = False
    emits_artifacts = False

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "process_id": {
                    "type": "string",
                    "description": "Process handle from shell:start",
                },
                "max_bytes": {
                    "type": "integer",
                    "description": "Maximum bytes to include in tail",
                    "minimum": 1,
                },
            },
            "required": ["process_id"],
        }

    async def execute(
        self, process_id: str, max_bytes: int | None = None, **kwargs: Any
    ) -> ToolResult:
        state = _get_process(process_id)
        if state is None:
            return ToolResult(False, "", error=f"Unknown process_id: {process_id}")

        poll_cfg = kwargs.get("process_poll") or DesktopOpsProcessPollConfig()
        max_bytes = int(max_bytes or getattr(poll_cfg, "max_bytes", 4000))
        with state.lock:
            stdout_tail = state.stdout_tail[-max_bytes:]
            stderr_tail = state.stderr_tail[-max_bytes:]
            bytes_stdout_total = state.bytes_stdout_total
            bytes_stderr_total = state.bytes_stderr_total
            last_output_at = state.last_output_at

        running = state.process.poll() is None
        exit_code = None if running else state.process.returncode

        truncated_stdout = bytes_stdout_total > max_bytes
        truncated_stderr = bytes_stderr_total > max_bytes
        last_output_at_iso = last_output_at.isoformat() + "Z" if last_output_at else None
        stalled = False
        if running and last_output_at:
            idle = datetime.utcnow() - last_output_at
            stalled = idle.total_seconds() > poll_cfg.max_idle_seconds

        payload = {
            "data": {
                "process_id": process_id,
                "pid": int(state.process.pid),
                "running": running,
                "exit_code": exit_code,
                "stdout_tail": stdout_tail.decode("utf-8", errors="replace"),
                "stderr_tail": stderr_tail.decode("utf-8", errors="replace"),
                "bytes_stdout_total": bytes_stdout_total,
                "bytes_stderr_total": bytes_stderr_total,
                "last_output_at": last_output_at_iso,
                "stalled": stalled,
            },
            "meta": {
                "truncated_stdout": truncated_stdout,
                "truncated_stderr": truncated_stderr,
            },
        }
        return ToolResult(True, _json(payload))


class BuiltinShellKillTool(BaseTool):
    name = "kill"
    description = "Stop a running process."
    server_id = "shell"
    risk_level = "exec"
    requires_shell = True
    mutates_state = True
    emits_artifacts = False

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "process_id": {
                    "type": "string",
                    "description": "Process handle from shell:start",
                },
                "force": {
                    "type": "boolean",
                    "description": "Force kill the process",
                    "default": False,
                },
            },
            "required": ["process_id"],
        }

    async def execute(self, process_id: str, force: bool = False, **kwargs: Any) -> ToolResult:
        state = _get_process(process_id)
        if state is None:
            return ToolResult(False, "", error=f"Unknown process_id: {process_id}")

        killed = False
        if state.process.poll() is None:
            try:
                if force:
                    state.process.kill()
                else:
                    state.process.terminate()
                killed = True
            except Exception as exc:
                return ToolResult(False, "", error=str(exc))

        payload = {
            "data": {
                "process_id": process_id,
                "pid": int(state.process.pid),
                "killed": killed,
                "force_used": bool(force),
            }
        }
        return ToolResult(True, _json(payload))


class BuiltinShellRunTool(BaseTool):
    name = "run"
    description = "Run a command and return its output."
    server_id = "shell"
    risk_level = "exec"
    requires_shell = True
    mutates_state = True
    emits_artifacts = False
    path_params = ("cwd",)
    path_params_optional = True
    uses_filesystem_paths = True

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "argv": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Command argv list",
                },
                "cwd": {"type": "string", "description": "Working directory"},
                "env": {
                    "type": "object",
                    "additionalProperties": {"type": "string"},
                    "description": "Environment variables to merge",
                },
                "timeout_seconds": {
                    "type": "integer",
                    "description": "Timeout for entire run in seconds",
                    "minimum": 1,
                },
            },
            "required": ["argv"],
        }

    async def execute(
        self,
        argv: list[str],
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        timeout_seconds: int | None = None,
        **kwargs: Any,
    ) -> ToolResult:
        if not isinstance(argv, list) or not argv:
            return ToolResult(False, "", error="argv must be a non-empty list of strings")
        try:
            resolved_cwd = _resolve_cwd(
                cwd,
                workspace=kwargs.get("workspace"),
                allowed_paths=kwargs.get("allowed_paths"),
                denied_paths=kwargs.get("denied_paths"),
            )
        except FileToolError as exc:
            return ToolResult(False, "", error=str(exc))

        argv_list = _normalize_argv(argv)
        try:
            process = subprocess.Popen(
                argv_list,
                cwd=str(resolved_cwd),
                env=_merge_env(env),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except Exception as exc:
            return ToolResult(False, "", error=str(exc))

        timed_out = False
        try:
            stdout, stderr = process.communicate(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            process.kill()
            stdout, stderr = process.communicate()

        stdout_text = (stdout or b"").decode("utf-8", errors="replace")
        stderr_text = (stderr or b"").decode("utf-8", errors="replace")
        exit_code = int(process.returncode) if process.returncode is not None else None
        payload = {
            "data": {
                "exit_code": exit_code,
                "stdout": stdout_text,
                "stderr": stderr_text,
                "timed_out": timed_out,
            }
        }
        success = exit_code == 0 and not timed_out
        error = None
        if timed_out:
            error = "Command timed out"
        elif exit_code not in (0, None):
            error = f"Command exited with code {exit_code}"
        return ToolResult(
            success,
            _json(payload),
            error=error,
            metadata={"exit_code": exit_code, "timed_out": timed_out},
        )
