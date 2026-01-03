"""Desktop Ops execution controller."""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Iterable

from aries.config import DesktopOpsConfig
from aries.core.message import ToolCall
from aries.core.workspace import resolve_and_validate_path
from aries.tools.base import ToolResult
from aries.ui.display import display_info, display_warning
from aries.ui.input import get_user_input


class DesktopOpsMode(str, Enum):
    GUIDE = "guide"
    COMMANDER = "commander"
    STRICT = "strict"


class DesktopRisk(str, Enum):
    READ_ONLY = "READ_ONLY"
    WRITE_SAFE = "WRITE_SAFE"
    WRITE_DESTRUCTIVE = "WRITE_DESTRUCTIVE"
    EXEC_USERSPACE = "EXEC_USERSPACE"
    EXEC_PRIVILEGED = "EXEC_PRIVILEGED"
    NETWORK = "NETWORK"


@dataclass
class ApprovalRecord:
    risk: DesktopRisk
    approved: bool
    scope: str
    reason: str
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class ProcessHandle:
    process_id: str
    started_at: datetime
    last_output_at: datetime
    last_output: str = ""


@dataclass
class RunContext:
    goal: str
    cwd: Path
    repo_root: Path | None
    virtualenv: str | None
    mode: DesktopOpsMode
    approvals: dict[DesktopRisk, ApprovalRecord] = field(default_factory=dict)
    active_processes: dict[str, ProcessHandle] = field(default_factory=dict)
    audit_log: list[dict[str, Any]] = field(default_factory=list)
    step_index: int = 0
    allowed_roots: list[Path] = field(default_factory=list)


@dataclass
class DesktopOpsResult:
    status: str
    summary: str
    audit_log: list[dict[str, Any]]
    artifacts: list[dict[str, Any]]
    run_log_path: Path | None = None


_RECIPE_PREFIX = "desktop.recipe."


class DesktopOpsController:
    """Controller implementing the Desktop Ops action loop."""

    def __init__(self, app: Any, *, mode: str | None = None) -> None:
        self.app = app
        self.config: DesktopOpsConfig = app.config.desktop_ops
        self.mode = DesktopOpsMode(mode or self.config.mode)
        self.max_steps = self.config.max_steps
        self.max_retries = self.config.max_retries_per_step

    async def run(self, goal: str) -> DesktopOpsResult:
        context = self._build_context(goal)
        artifacts: list[dict[str, Any]] = []

        system_prompt = self._build_system_prompt()
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": goal},
        ]

        if self.mode == DesktopOpsMode.GUIDE:
            plan = await self._propose_plan(goal)
            if plan:
                display_info("Desktop Ops plan:\n" + plan)
            proceed = await get_user_input("Proceed with this plan? [y/N]: ")
            if proceed.strip().lower() not in {"y", "yes"}:
                return DesktopOpsResult(
                    status="stopped",
                    summary="Desktop Ops stopped before execution.",
                    audit_log=context.audit_log,
                    artifacts=artifacts,
                )

        tool_definitions = self._tool_definitions()
        retry_counts: dict[str, int] = {}

        for step_index in range(self.max_steps):
            context.step_index = step_index
            response = await self.app.ollama.chat(
                model=self.app.current_model,
                messages=messages,
                tools=tool_definitions,
                raw=True,
            )
            message_payload = response.get("message", {}) if isinstance(response, dict) else {}
            tool_calls_raw = message_payload.get("tool_calls") or []

            if not tool_calls_raw:
                content = (message_payload.get("content") or "").strip()
                if self._is_done(content):
                    summary = content or "Desktop Ops completed."
                    return await self._finalize(context, "completed", summary, artifacts)
                question = self._extract_question(content)
                if question:
                    answer = await get_user_input(f"{question} ")
                    messages.append({"role": "user", "content": answer})
                    continue
                display_warning("Desktop Ops halted: no actionable tool call or completion signal.")
                return await self._finalize(context, "stopped", "Desktop Ops stopped without completion.", artifacts)

            tool_calls = self.app.conversation.parse_tool_calls(tool_calls_raw)
            for call in tool_calls:
                result = await self._execute_call(context, call)
                artifacts.extend(result.get("artifacts", []))
                messages.append(result["message"])

                if not result["success"]:
                    attempts = retry_counts.get(call.name, 0) + 1
                    retry_counts[call.name] = attempts
                    if attempts > self.max_retries:
                        failure_summary = f"Desktop Ops failed after {attempts} attempt(s) for {call.name}."
                        return await self._finalize(context, "failed", failure_summary, artifacts)

        return await self._finalize(
            context,
            "stopped",
            "Desktop Ops stopped after reaching max steps.",
            artifacts,
        )

    def _build_context(self, goal: str) -> RunContext:
        cwd = Path.cwd()
        repo_root = self._find_repo_root(cwd)
        virtualenv = self._virtualenv_name()
        allowed_roots = self._allowed_roots()
        return RunContext(
            goal=goal,
            cwd=cwd,
            repo_root=repo_root,
            virtualenv=virtualenv,
            mode=self.mode,
            allowed_roots=allowed_roots,
        )

    def _build_system_prompt(self) -> str:
        return (
            "You are Desktop Ops inside ARIES. "
            f"Active mode: {self.mode.value}. "
            "Operate in a plan→act→observe→adjust loop. "
            "Infer the next obvious step when unambiguous. "
            "Never assume success; always read tool output before proceeding. "
            "Self-correct common failures (missing dependencies, wrong working directory, "
            "virtualenv issues, permissions). "
            "Ask a single short clarifying question only when required. "
            "When finished, reply with DONE and a brief completion summary."
        )

    async def _propose_plan(self, goal: str) -> str:
        response = await self.app.ollama.chat(
            model=self.app.current_model,
            messages=[
                {"role": "system", "content": "Provide a short numbered plan."},
                {"role": "user", "content": f"Plan the steps to: {goal}"},
            ],
            raw=True,
        )
        content = response.get("message", {}).get("content", "") if isinstance(response, dict) else ""
        return content.strip()

    def _tool_definitions(self) -> list[dict[str, Any]]:
        definitions = list(self.app.tool_registry.list_tool_definitions(qualified=True))
        definitions.extend(self._recipe_tool_definitions())
        return definitions

    def _recipe_tool_definitions(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": f"{_RECIPE_PREFIX}repo_clone_open",
                    "description": "Clone a repository and open it in the workspace.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "repo_url": {"type": "string"},
                            "dest": {"type": "string"},
                        },
                        "required": ["repo_url", "dest"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": f"{_RECIPE_PREFIX}python_bootstrap",
                    "description": "Create a virtualenv and install dependencies.",
                    "parameters": {
                        "type": "object",
                        "properties": {"path": {"type": "string"}},
                        "required": ["path"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": f"{_RECIPE_PREFIX}run_tests",
                    "description": "Run tests using pytest or unittest.",
                    "parameters": {
                        "type": "object",
                        "properties": {"path": {"type": "string"}},
                        "required": ["path"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": f"{_RECIPE_PREFIX}build_project",
                    "description": "Build the project using common build commands.",
                    "parameters": {
                        "type": "object",
                        "properties": {"path": {"type": "string"}},
                        "required": ["path"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": f"{_RECIPE_PREFIX}log_tail",
                    "description": "Start, stream, and stop a log tailing process.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"},
                            "lines": {"type": "integer"},
                        },
                        "required": ["path"],
                    },
                },
            },
        ]

    async def _execute_call(self, context: RunContext, call: ToolCall) -> dict[str, Any]:
        if call.name.startswith(_RECIPE_PREFIX):
            return await self._execute_recipe(context, call)

        tool_id, tool, error = self.app._resolve_tool_reference(call.name)
        if error or tool is None:
            context.audit_log.append(
                {"event": "tool_resolution_failed", "tool": call.name, "error": error}
            )
        return self._tool_message(call.id, call.name, False, error or "Unknown tool.")

        risk = self._classify_risk(tool, call.arguments)
        approved, approval_reason, allowed_paths = await self._check_approval(
            context, risk, tool, call.arguments
        )
        if not approved:
            context.audit_log.append(
                {
                    "event": "approval_denied",
                    "tool": call.name,
                    "risk": risk.value,
                    "reason": approval_reason,
                }
            )
            return self._tool_message(call.id, call.name, False, f"Approval denied ({approval_reason}).")

        tool_result, audit = await self.app._run_tool(
            tool,
            call,
            tool_id,
            allowed_paths=allowed_paths,
        )
        self._record_tool_audit(context, tool, call, tool_result, audit, risk, approval_reason)

        if tool_result.success and tool_result.artifacts:
            for artifact in tool_result.artifacts:
                context.audit_log.append({"event": "artifact", "artifact": artifact})

        await self._maybe_stream_process_output(context, tool, tool_result)
        content = tool_result.content if tool_result.success else (tool_result.error or "")
        return self._tool_message(call.id, call.name, tool_result.success, content, tool_result.artifacts)

    async def _execute_recipe(self, context: RunContext, call: ToolCall) -> dict[str, Any]:
        recipe = call.name[len(_RECIPE_PREFIX) :]
        handlers = {
            "repo_clone_open": self._recipe_repo_clone_open,
            "python_bootstrap": self._recipe_python_bootstrap,
            "run_tests": self._recipe_run_tests,
            "build_project": self._recipe_build_project,
            "log_tail": self._recipe_log_tail,
        }
        handler = handlers.get(recipe)
        if not handler:
            return self._tool_message(call.id, call.name, False, f"Unknown recipe: {recipe}")
        result = await handler(context, call.arguments)
        content = result.content if result.success else (result.error or "")
        return self._tool_message(call.id, call.name, result.success, content, result.artifacts)

    async def _recipe_repo_clone_open(self, context: RunContext, args: dict[str, Any]) -> ToolResult:
        repo_url = args.get("repo_url")
        dest = args.get("dest")
        if not repo_url or not dest:
            return ToolResult(success=False, content="", error="repo_url and dest are required")
        commands = [
            f"git clone {repo_url} {dest}",
            f"cd {dest} && git status -sb",
        ]
        return await self._run_shell_sequence(context, commands, label="repo_clone_open")

    async def _recipe_python_bootstrap(self, context: RunContext, args: dict[str, Any]) -> ToolResult:
        path = args.get("path")
        if not path:
            return ToolResult(success=False, content="", error="path is required")
        commands = [
            f"cd {path} && python -m venv .venv",
            f"cd {path} && . .venv/bin/activate && python -m pip install -U pip",
            f"cd {path} && . .venv/bin/activate && python -m pip install -r requirements.txt",
        ]
        return await self._run_shell_sequence(context, commands, label="python_bootstrap")

    async def _recipe_run_tests(self, context: RunContext, args: dict[str, Any]) -> ToolResult:
        path = args.get("path")
        if not path:
            return ToolResult(success=False, content="", error="path is required")
        commands = [
            f"cd {path} && pytest",
            f"cd {path} && python -m unittest discover",
        ]
        return await self._run_shell_sequence(context, commands, label="run_tests")

    async def _recipe_build_project(self, context: RunContext, args: dict[str, Any]) -> ToolResult:
        path = args.get("path")
        if not path:
            return ToolResult(success=False, content="", error="path is required")
        commands = [
            f"cd {path} && make build",
            f"cd {path} && npm run build",
        ]
        return await self._run_shell_sequence(context, commands, label="build_project")

    async def _recipe_log_tail(self, context: RunContext, args: dict[str, Any]) -> ToolResult:
        path = args.get("path")
        lines = args.get("lines", 50)
        if not path:
            return ToolResult(success=False, content="", error="path is required")
        command = f"tail -n {lines} -f {path}"
        return await self._run_shell_sequence(context, [command], label="log_tail")

    async def _run_shell_sequence(
        self, context: RunContext, commands: Iterable[str], *, label: str
    ) -> ToolResult:
        tool_id, tool, error = self.app._resolve_tool_reference("shell")
        if error or tool is None:
            return ToolResult(success=False, content="", error=error or "Shell tool unavailable")
        outputs: list[str] = []
        for cmd in commands:
            call = ToolCall(name=getattr(tool_id, "qualified", tool.name), arguments={"command": cmd})
            result, audit = await self.app._run_tool(tool, call, tool_id)
            self._record_tool_audit(
                context,
                tool,
                call,
                result,
                audit,
                self._classify_risk(tool, call.arguments),
                f"recipe:{label}",
            )
            if not result.success:
                return result
            outputs.append(result.content)
        return ToolResult(success=True, content="\n".join(outputs))

    async def _maybe_stream_process_output(
        self, context: RunContext, tool: Any, result: ToolResult
    ) -> None:
        if not result.success:
            return
        tool_name = getattr(tool, "name", "")
        if "start_process" not in tool_name:
            return
        metadata = result.metadata or {}
        process_id = metadata.get("process_id") or metadata.get("session_id") or metadata.get("pid")
        if not process_id:
            return
        handle = ProcessHandle(
            process_id=str(process_id),
            started_at=datetime.now(),
            last_output_at=datetime.now(),
        )
        context.active_processes[handle.process_id] = handle

        read_tool_id, read_tool = self._find_process_reader()
        if not read_tool:
            display_warning("Desktop Ops: process started but no read_process_output tool available.")
            return

        poll_cfg = self.config.process_poll
        delay = poll_cfg.initial_ms / 1000.0
        start_time = datetime.now()
        while True:
            elapsed = datetime.now() - start_time
            if elapsed.total_seconds() > poll_cfg.max_total_seconds:
                break
            output = await self._poll_process(read_tool, read_tool_id, handle)
            if output:
                handle.last_output = output
                handle.last_output_at = datetime.now()
                context.audit_log.append(
                    {"event": "process_output", "process_id": handle.process_id, "output": output}
                )
            idle = datetime.now() - handle.last_output_at
            if idle.total_seconds() > poll_cfg.max_idle_seconds:
                break
            await asyncio.sleep(delay)
            delay = min(delay * 2, poll_cfg.max_ms / 1000.0)

    async def _poll_process(self, tool: Any, tool_id: Any, handle: ProcessHandle) -> str:
        arg_name = self._process_arg_name(tool)
        if not arg_name:
            return ""
        call = ToolCall(
            name=getattr(tool_id, "qualified", tool.name),
            arguments={arg_name: handle.process_id},
        )
        result, audit = await self.app._run_tool(tool, call, tool_id)
        if result.success:
            truncated, truncated_flag = self._truncate_output(result.content)
            if truncated_flag:
                summary = self._summarize_output(result.content)
                return f"{truncated}\n{summary}"
            return result.content
        return result.error or ""

    def _find_process_reader(self) -> tuple[Any | None, Any | None]:
        for name in ("read_process_output", "process_read", "read_process"):
            resolved = self.app.tool_registry.resolve_with_id(name)
            if resolved:
                tool_id, tool = resolved
                return tool_id, tool
        return None, None

    def _process_arg_name(self, tool: Any) -> str | None:
        schema = getattr(tool, "parameters", {}) or {}
        props = schema.get("properties") if isinstance(schema, dict) else {}
        for candidate in ("process_id", "session_id", "pid", "handle"):
            if candidate in props:
                return candidate
        return None

    def _record_tool_audit(
        self,
        context: RunContext,
        tool: Any,
        call: ToolCall,
        result: ToolResult,
        audit: dict[str, Any],
        risk: DesktopRisk,
        approval_reason: str,
    ) -> None:
        entry = {
            "event": "tool_call",
            "tool": call.name,
            "risk": risk.value,
            "approval_reason": approval_reason,
            "success": result.success,
            "error": result.error,
            "audit": audit,
        }
        context.audit_log.append(entry)

    async def _check_approval(
        self,
        context: RunContext,
        risk: DesktopRisk,
        tool: Any,
        args: dict[str, Any],
    ) -> tuple[bool, str, list[Path] | None]:
        approval_reason = "auto"
        allowed_paths = None

        if self._requires_path_override(context, tool, args):
            approved = await self._request_path_override(context, tool, args)
            if not approved:
                return False, "path_outside_workspace", None
            allowed_paths = self._approved_paths(context, tool, args)
            approval_reason = "path_outside_workspace"

        if not self._requires_approval(risk, tool, args):
            return True, approval_reason, allowed_paths

        cached = context.approvals.get(risk)
        if cached and cached.approved and cached.scope == "session":
            return True, cached.reason, allowed_paths

        prompt = self._approval_prompt(risk, tool, args)
        response = await get_user_input(prompt)
        approved = response.strip().lower() in {"y", "yes"}
        approval_reason = approval_reason if approval_reason != "auto" else "manual"
        scope = "session" if approved else "denied"
        record = ApprovalRecord(
            risk=risk,
            approved=approved,
            scope=scope,
            reason=approval_reason,
        )
        context.approvals[risk] = record
        return approved, approval_reason or "manual", allowed_paths

    def _requires_approval(self, risk: DesktopRisk, tool: Any, args: dict[str, Any]) -> bool:
        if self.mode == DesktopOpsMode.STRICT:
            return True
        if risk.value in self.config.require_approval_for:
            return True
        if self.mode == DesktopOpsMode.GUIDE:
            return risk not in {DesktopRisk.READ_ONLY}
        if self.mode == DesktopOpsMode.COMMANDER:
            if risk == DesktopRisk.EXEC_USERSPACE and self._allowlisted(tool, args):
                return False
            return risk not in {DesktopRisk.READ_ONLY, DesktopRisk.WRITE_SAFE}
        return False

    def _allowlisted(self, tool: Any, args: dict[str, Any]) -> bool:
        command = args.get("command")
        qualified = getattr(tool, "qualified_id", tool.name)
        normalized = getattr(tool, "normalized_id", None)
        candidates = [
            f"{qualified}:{command}" if command else qualified,
            f"{normalized}:{command}" if normalized and command else normalized,
        ]
        for entry in self.config.auto_exec_allowlist:
            if entry in candidates:
                return True
        return False

    def _approval_prompt(self, risk: DesktopRisk, tool: Any, args: dict[str, Any]) -> str:
        tool_name = getattr(tool, "qualified_id", tool.name)
        return f"Approve {risk.value} for {tool_name}? [y/N]: "

    def _requires_path_override(self, context: RunContext, tool: Any, args: dict[str, Any]) -> bool:
        path_params = getattr(tool, "path_params", ()) or ()
        for param in path_params:
            value = args.get(param)
            if not value:
                continue
            if self._path_outside_workspace(context, value):
                return True
        return False

    def _path_outside_workspace(self, context: RunContext, value: str) -> bool:
        try:
            resolve_and_validate_path(
                value,
                workspace=self.app.workspace.current,
                allowed_paths=context.allowed_roots,
            )
            return False
        except Exception:
            return True

    async def _request_path_override(self, context: RunContext, tool: Any, args: dict[str, Any]) -> bool:
        prompt = f"Path outside workspace requested by {getattr(tool, 'qualified_id', tool.name)}. Allow? [y/N]: "
        response = await get_user_input(prompt)
        approved = response.strip().lower() in {"y", "yes"}
        context.audit_log.append(
            {
                "event": "path_override",
                "tool": getattr(tool, "qualified_id", tool.name),
                "approved": approved,
                "args": args,
            }
        )
        return approved

    def _approved_paths(self, context: RunContext, tool: Any, args: dict[str, Any]) -> list[Path]:
        paths: list[Path] = []
        path_params = getattr(tool, "path_params", ()) or ()
        for param in path_params:
            value = args.get(param)
            if not value:
                continue
            try:
                resolved = resolve_and_validate_path(value, workspace=self.app.workspace.current)
            except Exception:
                resolved = Path(value).expanduser().resolve()
            paths.append(resolved)
        base = [Path(p).expanduser().resolve() for p in context.allowed_roots]
        return list({*base, *paths})

    def _classify_risk(self, tool: Any, args: dict[str, Any]) -> DesktopRisk:
        desktop_risk = getattr(tool, "desktop_risk", None)
        if desktop_risk:
            return DesktopRisk(desktop_risk)
        if getattr(tool, "requires_network", False):
            return DesktopRisk.NETWORK
        risk_level = str(getattr(tool, "risk_level", "read")).lower()
        mutates = bool(getattr(tool, "mutates_state", False))
        if risk_level == "read":
            return DesktopRisk.READ_ONLY
        if risk_level == "write":
            return DesktopRisk.WRITE_DESTRUCTIVE if mutates else DesktopRisk.WRITE_SAFE
        if getattr(tool, "requires_shell", False):
            return DesktopRisk.EXEC_USERSPACE
        return DesktopRisk.EXEC_USERSPACE

    async def _finalize(
        self,
        context: RunContext,
        status: str,
        summary: str,
        artifacts: list[dict[str, Any]],
    ) -> DesktopOpsResult:
        run_log_path = self._write_audit_log(context)
        return DesktopOpsResult(
            status=status,
            summary=summary,
            audit_log=context.audit_log,
            artifacts=artifacts,
            run_log_path=run_log_path,
        )

    def _write_audit_log(self, context: RunContext) -> Path | None:
        if not self.app.workspace.current:
            return None
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = self.app.workspace.current.artifact_dir / f"desktop_ops_{timestamp}.json"
        payload = {
            "goal": context.goal,
            "mode": context.mode.value,
            "cwd": str(context.cwd),
            "repo_root": str(context.repo_root) if context.repo_root else None,
            "virtualenv": context.virtualenv,
            "audit_log": context.audit_log,
        }
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        self.app.workspace.register_artifact_hint(path, source="desktop_ops")
        return path

    def _tool_message(
        self,
        tool_call_id: str,
        tool_name: str,
        success: bool,
        content: str,
        artifacts: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        message = {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "name": tool_name,
            "content": content or "",
        }
        return {
            "success": success,
            "message": message,
            "artifacts": artifacts or [],
        }

    def _is_done(self, content: str) -> bool:
        if not content:
            return False
        upper = content.strip().upper()
        return upper.startswith("DONE") or upper.startswith("COMPLETE")

    def _extract_question(self, content: str) -> str | None:
        if not content:
            return None
        markers = ("QUESTION:", "CLARIFY:", "NEED INPUT:")
        for marker in markers:
            if marker in content.upper():
                parts = content.split(":", 1)
                return parts[1].strip() if len(parts) > 1 else content
        return None

    def _find_repo_root(self, cwd: Path) -> Path | None:
        current = cwd
        while current != current.parent:
            if (current / ".git").exists():
                return current
            current = current.parent
        return None

    def _virtualenv_name(self) -> str | None:
        return str(Path(venv).name) if (venv := self._env("VIRTUAL_ENV")) else None

    def _env(self, key: str) -> str | None:
        return os.environ.get(key)

    def _allowed_roots(self) -> list[Path]:
        roots = [Path(p).expanduser().resolve() for p in self.config.allowed_roots]
        if self.app.workspace.current:
            roots.append(self.app.workspace.current.root)
        return roots

    def _truncate_output(self, text: str, limit: int = 4000) -> tuple[str, bool]:
        if len(text) <= limit:
            return text, False
        return text[:limit] + "\n...[truncated]", True

    def _summarize_output(self, text: str, lines: int = 20) -> str:
        tail = "\n".join(text.splitlines()[-lines:])
        return f"(output truncated; last {lines} lines)\n{tail}"
