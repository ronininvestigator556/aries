"""Desktop Ops execution controller."""

from __future__ import annotations

import asyncio
import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from hashlib import sha256
from pathlib import Path
from typing import Any

from aries.config import DesktopOpsConfig
from aries.core.desktop_recipes import DesktopRecipeRegistry, RecipeStep, recipe_prefix
from aries.core.desktop_summary import SummaryBuilder, SummaryOutcome
from aries.core.file_edit import FileEditPipeline
from aries.core.message import ToolCall
from aries.core.workspace import resolve_and_validate_path
from aries.exceptions import FileToolError
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
    raw_output_path: Path | None = None
    output_condenser: OutputCondenser | None = None


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
    policy_cache: dict[str, dict[str, Any]] = field(default_factory=dict)
    path_cache: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass
class DesktopOpsResult:
    status: str
    summary: str
    audit_log: list[dict[str, Any]]
    artifacts: list[dict[str, Any]]
    run_log_path: Path | None = None


class DesktopOpsController:
    """Controller implementing the Desktop Ops action loop."""

    def __init__(
        self,
        app: Any,
        *,
        mode: str | None = None,
        summary_format: str | None = None,
    ) -> None:
        self.app = app
        self.config: DesktopOpsConfig = app.config.desktop_ops
        self.mode = DesktopOpsMode(mode or self.config.mode)
        self.summary_format = summary_format or self.config.summary_format
        self.max_steps = self.config.max_steps
        self.max_retries = self.config.max_retries_per_step
        self.recipe_registry = DesktopRecipeRegistry(self.config)
        self._file_edit_pipeline: FileEditPipeline | None = None

    async def run(self, goal: str) -> DesktopOpsResult:
        context = self._build_context(goal)
        artifacts: list[dict[str, Any]] = []
        self._update_desktop_status(context, recipe=None)

        system_prompt = self._build_system_prompt()
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": goal},
        ]

        if self.mode == DesktopOpsMode.GUIDE:
            plan = await self._propose_plan(goal)
            if plan:
                display_info("Desktop Ops plan:\n" + plan)
            proceed = await get_user_input("Proceed with this plan? [y/N]: ")
            if proceed.strip().lower() not in {"y", "yes"}:
                return await self._finalize(
                    context,
                    "stopped",
                    "Desktop Ops stopped before execution.",
                    artifacts,
                )

        if not self._has_executable_tools():
            return await self._finalize(
                context,
                "failed",
                "Desktop Ops requires a configured provider (desktop_commander or filesystem). "
                "Configure in config.yaml.",
                artifacts,
            )

        tool_definitions = self._tool_definitions()
        retry_counts: dict[str, int] = {}
        recipe_attempted = False
        nudge_count = 0
        max_nudges = 3

        preferred_recipe = self.recipe_registry.match_goal(goal, context)
        if preferred_recipe:
            context.audit_log.append(
                {
                    "event": "recipe_preference",
                    "recipe": preferred_recipe.name,
                    "arguments": preferred_recipe.arguments,
                    "reason": preferred_recipe.reason,
                }
            )
            recipe_call = ToolCall(
                id="recipe_preference",
                name=f"{recipe_prefix()}{preferred_recipe.name}",
                arguments=preferred_recipe.arguments,
            )
            result = await self._execute_recipe(context, recipe_call)
            recipe_attempted = True
            artifacts.extend(result.get("artifacts", []))
            if result.get("success"):
                return await self._finalize(
                    context,
                    "completed",
                    result.get("message", {}).get("content") or "Desktop Ops completed.",
                    artifacts,
                )
            messages.append(result.get("message"))

        for step_index in range(self.max_steps):
            context.step_index = step_index
            response = await self.app.ollama.chat(
                model=self.app.current_model,
                messages=messages,
                tools=tool_definitions,
                raw=True,
            )
            message_payload = response.get("message", {}) if isinstance(response, dict) else {}
            content = (message_payload.get("content") or "").strip()
            tool_calls_raw = message_payload.get("tool_calls") or []

            # Append assistant message to history immediately to maintain context
            messages.append(message_payload)

            context.audit_log.append(
                {
                    "event": "llm_response",
                    "step": step_index,
                    "content": content,
                    "tool_calls": tool_calls_raw,
                }
            )

            if not tool_calls_raw:
                if content:
                    display_info(f"Assistant: {content}")

                if self._is_done(content):
                    summary = content or "Desktop Ops completed."
                    return await self._finalize(context, "completed", summary, artifacts)

                # Check if task appears complete based on context
                if self._task_appears_complete(context, content):
                    display_info("Task appears complete based on analysis.")
                    summary = content or "Desktop Ops completed the requested task."
                    return await self._finalize(context, "completed", summary, artifacts)

                question = self._extract_question(content)
                if question:
                    answer = await get_user_input(f"{question} ")
                    messages.append({"role": "user", "content": answer})
                    continue
                if self.mode == DesktopOpsMode.COMMANDER and not recipe_attempted:
                    recipe_result = await self._attempt_recipe_fallback(
                        context,
                        artifacts,
                        goal,
                    )
                    recipe_attempted = True
                    if recipe_result:
                        return recipe_result
                if self.mode == DesktopOpsMode.GUIDE:
                    return await self._finalize(
                        context,
                        "stopped",
                        "No actionable tool call. Try /desktop --plan and consider switching models.",
                        artifacts,
                    )

                # If we have content but no tool calls and it's not a question/done,
                # give the model a chance to self-correct with a nudge.
                if content and nudge_count < max_nudges:
                    nudge_count += 1

                    # Provide more specific guidance based on the content
                    nudge_message = (
                        "CRITICAL: You must either use a tool call OR explicitly say 'DONE'.\n\n"
                        "If the task is complete:\n"
                        "- Respond with exactly: 'DONE: <brief summary of what was accomplished>'\n\n"
                        "If you need to perform an action:\n"
                        "- Use the function calling mechanism to invoke a tool\n"
                        "- DO NOT describe what you would do - actually call the tool\n"
                        "- DO NOT write code blocks or markdown - use JSON tool calls\n\n"
                        "Available actions:\n"
                        "- Execute commands: call execute_command tool\n"
                        "- List files: call list_directory tool\n"
                        "- Read files: call read_file tool\n"
                        "- Write files: call write_file tool\n\n"
                        "If you're asking a question, prefix it with 'QUESTION:' so I can prompt the user."
                    )

                    messages.append({
                        "role": "system",
                        "content": nudge_message
                    })
                    display_warning(f"No tool call provided; nudging model (attempt {nudge_count}/{max_nudges})...")
                    continue

                display_warning("Desktop Ops halted: no actionable tool call or completion signal.")
                return await self._finalize(
                    context,
                    "stopped",
                    "Desktop Ops stopped without completion.",
                    artifacts,
                )

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

    async def plan(self, goal: str, *, dry_run: bool = False) -> tuple[str, list[dict[str, Any]]]:
        context = self._build_context(goal)
        self._update_desktop_status(context, recipe=None)
        recipe_match = self.recipe_registry.match_goal(goal, context)
        plan = None
        recipe_name = None
        if recipe_match:
            recipe_name = recipe_match.name
            plan = self.recipe_registry.plan(recipe_match.name, recipe_match.arguments, context)
            context.audit_log.append(
                {
                    "event": "recipe_plan",
                    "recipe": recipe_match.name,
                    "steps": [
                        {
                            "name": step.name,
                            "tool": step.tool_name,
                            "description": step.description,
                        }
                        for step in plan.steps
                    ],
                }
            )

        if not plan:
            manual_plan_text = await self._propose_plan(goal)
            plan_output = f"Desktop Ops plan\nRecipe: manual plan\n\n{manual_plan_text}"
            self._update_desktop_status(context, recipe=None)
            return plan_output, context.audit_log

        plan_output = self._format_plan_output(
            context,
            plan,
            recipe_name=recipe_name,
            dry_run=dry_run,
        )

        if dry_run and plan:
            await self._run_dry_run_probes(context, plan)

        self._update_desktop_status(context, recipe=None)
        return plan_output, context.audit_log

    def _build_system_prompt(self) -> str:
        return (
            "You are Desktop Ops inside ARIES. "
            f"Active mode: {self.mode.value}. "
            "Your goal is to complete the user's request using the available tools. "
            "Operate in a plan→act→observe→adjust loop. "
            "\n\n"
            "CRITICAL RULES:\n"
            "1. ALWAYS use tool calls (function calls) to perform actions - NEVER just describe them\n"
            "2. When the requested task is complete, respond with: 'DONE: <summary>'\n"
            "3. If you need clarification, prefix your question with 'QUESTION:'\n"
            "4. DO NOT ask for next steps after completing a task - just say DONE\n"
            "\n\n"
            "Tool Usage:\n"
            "- Execute commands: use execute_command tool (not descriptions)\n"
            "- List files: use list_directory tool\n"
            "- Read files: use read_file tool\n"
            "- Write files: use write_file tool\n"
            "\n\n"
            "Important Guidelines:\n"
            "- Infer the next obvious step when unambiguous\n"
            "- Never assume success; always read tool output before proceeding\n"
            "- Self-correct common failures (missing dependencies, wrong working directory, virtualenv issues, permissions)\n"
            "- Only ask for clarification when truly necessary (not after completing the task)\n"
            "- When you've accomplished what was requested, say 'DONE: <what you did>' - do not ask for more work"
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
        definitions.extend(self.recipe_registry.definitions())
        return definitions

    def _has_executable_tools(self) -> bool:
        return bool(self.app.tool_registry.list_tools())

    async def _attempt_recipe_fallback(
        self,
        context: RunContext,
        artifacts: list[dict[str, Any]],
        goal: str,
    ) -> DesktopOpsResult | None:
        preferred_recipe = self.recipe_registry.match_goal(goal, context)
        if not preferred_recipe:
            return None
        recipe_call = ToolCall(
            id="recipe_fallback",
            name=f"{recipe_prefix()}{preferred_recipe.name}",
            arguments=preferred_recipe.arguments,
        )
        result = await self._execute_recipe(context, recipe_call)
        artifacts.extend(result.get("artifacts", []))
        if result.get("success"):
            return await self._finalize(
                context,
                "completed",
                result.get("message", {}).get("content") or "Desktop Ops completed.",
                artifacts,
            )
        return None

    async def _execute_call(self, context: RunContext, call: ToolCall) -> dict[str, Any]:
        if call.name.startswith(recipe_prefix()):
            return await self._execute_recipe(context, call)

        tool_id, tool, error = self.app._resolve_tool_reference(call.name)
        if error or tool is None:
            context.audit_log.append(
                {"event": "tool_resolution_failed", "tool": call.name, "error": error}
            )
            return self._tool_message(call.id, call.name, False, error or "Unknown tool.")

        tool_result, audit, policy_entry = await self._execute_tool_call_with_policy(
            context,
            tool,
            tool_id,
            call,
        )
        if not policy_entry["approval_result"]:
            return self._tool_message(
                call.id,
                call.name,
                False,
                f"Approval denied ({policy_entry['approval_reason']}).",
            )

        if tool_result.success and tool_result.artifacts:
            for artifact in tool_result.artifacts:
                context.audit_log.append({"event": "artifact", "artifact": artifact})

        await self._maybe_stream_process_output(context, tool, tool_result)
        content = tool_result.content if tool_result.success else (tool_result.error or "")
        return self._tool_message(call.id, call.name, tool_result.success, content, tool_result.artifacts)

    async def _execute_recipe(self, context: RunContext, call: ToolCall) -> dict[str, Any]:
        recipe = call.name[len(recipe_prefix()) :]
        self._update_desktop_status(context, recipe=recipe)
        try:
            plan = self.recipe_registry.plan(recipe, call.arguments, context)
        except Exception as exc:
            return self._tool_message(call.id, call.name, False, str(exc))

        context.audit_log.append(
            {
                "event": "recipe_plan",
                "recipe": recipe,
                "steps": [
                    {
                        "name": step.name,
                        "tool": step.tool_name,
                        "description": step.description,
                    }
                    for step in plan.steps
                ],
            }
        )

        max_seconds = call.arguments.get("max_seconds") if recipe == "log_tail" else None
        step_results: list[dict[str, Any]] = []
        artifacts: list[dict[str, Any]] = []
        last_result: dict[str, Any] | None = None

        steps_queue = list(plan.steps)
        while steps_queue:
            step = steps_queue.pop(0)
            step_args = step.arguments(context, last_result) if callable(step.arguments) else step.arguments
            if not step_args and step.tool_name == "stop_process":
                context.audit_log.append(
                    {
                        "event": "recipe_step_skipped",
                        "recipe": recipe,
                        "step": step.name,
                        "reason": "missing_process_id",
                    }
                )
                continue
            tool_id, tool, error = self._resolve_recipe_tool(step)
            if error or tool is None:
                context.audit_log.append(
                    {
                        "event": "recipe_step_failed",
                        "recipe": recipe,
                        "step": step.name,
                        "error": error or "Tool unavailable",
                    }
                )
                return self._tool_message(call.id, call.name, False, error or "Tool unavailable")

            tool_call = ToolCall(
                id=f"recipe:{recipe}:{step.name}",
                name=getattr(tool_id, "qualified", tool.name),
                arguments=step_args,
            )
            result, audit, policy_entry = await self._execute_tool_call_with_policy(
                context,
                tool,
                tool_id,
                tool_call,
                recipe=recipe,
                step=step.name,
            )
            if not policy_entry["approval_result"]:
                return self._tool_message(
                    call.id,
                    call.name,
                    False,
                    f"Approval denied ({policy_entry['approval_reason']}).",
                )
            step_results.append(
                {
                    "step": step.name,
                    "tool": tool_call.name,
                    "success": result.success,
                    "output": result.content if result.success else (result.error or ""),
                    "metadata": result.metadata or {},
                }
            )

            if result.artifacts:
                artifacts.extend(result.artifacts)
                for artifact in result.artifacts:
                    context.audit_log.append({"event": "artifact", "artifact": artifact})

            override = max_seconds if step.name == "start_tail" else None
            await self._maybe_stream_process_output(context, tool, result, max_total_seconds=override)

            if not result.success:
                output = result.error or result.content or ""
                if step.on_failure:
                    followups = list(step.on_failure(output))
                    if followups:
                        steps_queue = followups + steps_queue
                        last_result = {
                            "success": result.success,
                            "output": output,
                            "metadata": result.metadata or {},
                        }
                        continue
                content = result.error or ""
                return self._tool_message(call.id, call.name, False, content, artifacts)

            last_result = {
                "success": result.success,
                "output": result.content,
                "metadata": result.metadata or {},
            }

        done = plan.done_criteria(context, step_results)
        if not done:
            return self._tool_message(
                call.id,
                call.name,
                False,
                "Recipe did not meet completion criteria.",
                artifacts,
            )
        summary = plan.summary or "Recipe completed."
        self._update_desktop_status(context, recipe=None)
        return self._tool_message(call.id, call.name, True, summary, artifacts)

    def _resolve_recipe_tool(self, step: RecipeStep) -> tuple[Any | None, Any | None, str | None]:
        fallback_names = [step.tool_name]
        if step.tool_name == "stop_process":
            fallback_names.extend(["terminate_process", "kill_process"])
        for name in fallback_names:
            tool_id, tool, error = self.app._resolve_tool_reference(name)
            if tool:
                return tool_id, tool, None
        return None, None, error or f"Tool {step.tool_name} unavailable"

    async def _maybe_stream_process_output(
        self,
        context: RunContext,
        tool: Any,
        result: ToolResult,
        *,
        max_total_seconds: float | None = None,
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
            output_condenser=OutputCondenser(),
        )
        self._initialize_process_artifact(context, handle)
        context.active_processes[handle.process_id] = handle
        self._update_desktop_status(context, recipe=None)

        read_tool_id, read_tool = self._find_process_reader()
        if not read_tool:
            display_warning("Desktop Ops: process started but no read_process_output tool available.")
            return

        poll_cfg = self.config.process_poll
        if max_total_seconds is not None:
            max_total_seconds = float(max_total_seconds)
        delay = poll_cfg.initial_ms / 1000.0
        start_time = datetime.now()
        stalled = False
        while True:
            elapsed = datetime.now() - start_time
            if elapsed.total_seconds() > (max_total_seconds or poll_cfg.max_total_seconds):
                stalled = True
                break
            output = await self._poll_process(read_tool, read_tool_id, handle)
            if output:
                handle.last_output = output
                handle.last_output_at = datetime.now()
                self._append_process_output(handle, output)
                display_output = self._condense_process_output(handle, output)
                context.audit_log.append(
                    {
                        "event": "process_output",
                        "process_id": handle.process_id,
                        "output": display_output,
                        "raw_artifact": str(handle.raw_output_path) if handle.raw_output_path else None,
                    }
                )
                if display_output:
                    display_info(f"Process {handle.process_id}: {display_output}")
            idle = datetime.now() - handle.last_output_at
            if idle.total_seconds() > poll_cfg.max_idle_seconds:
                stalled = True
                break
            await asyncio.sleep(delay)
            delay = min(delay * 2, poll_cfg.max_ms / 1000.0)

        if stalled:
            context.audit_log.append(
                {"event": "process_stalled", "process_id": handle.process_id}
            )
            await self._stop_process(context, handle)

    async def _poll_process(self, tool: Any, tool_id: Any, handle: ProcessHandle) -> str:
        arg_name = self._process_arg_name(tool)
        if not arg_name:
            return ""
        call = ToolCall(
            id=f"process_read:{handle.process_id}",
            name=getattr(tool_id, "qualified", tool.name),
            arguments={arg_name: handle.process_id},
        )
        result, audit = await self.app._run_tool(tool, call, tool_id)
        if result.success:
            return result.content
        return result.error or ""

    async def _stop_process(self, context: RunContext, handle: ProcessHandle) -> None:
        tool_id, tool, error = self._resolve_recipe_tool(
            RecipeStep(name="stop_process", tool_name="stop_process", arguments={})
        )
        if error or tool is None:
            context.audit_log.append(
                {
                    "event": "process_stop_failed",
                    "process_id": handle.process_id,
                    "error": error or "Stop process tool unavailable",
                }
            )
            return
        arg_name = self._process_arg_name(tool)
        if not arg_name:
            context.audit_log.append(
                {
                    "event": "process_stop_failed",
                    "process_id": handle.process_id,
                    "error": "Stop process tool missing process id param",
                }
            )
            return
        tool_call = ToolCall(
            id=f"process_stop:{handle.process_id}",
            name=getattr(tool_id, "qualified", tool.name),
            arguments={arg_name: handle.process_id},
        )
        result, _, _ = await self._execute_tool_call_with_policy(
            context,
            tool,
            tool_id,
            tool_call,
            recipe="process_stream",
            step="stop_process",
        )
        context.audit_log.append(
            {
                "event": "process_stop",
                "process_id": handle.process_id,
                "success": result.success,
                "error": result.error,
            }
        )
        context.active_processes.pop(handle.process_id, None)
        self._update_desktop_status(context, recipe=None)

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
        *,
        probe: bool = False,
    ) -> None:
        entry = {
            "event": "tool_call",
            "tool": call.name,
            "risk": risk.value,
            "approval_reason": approval_reason,
            "success": result.success,
            "error": result.error,
            "audit": audit,
            "probe": probe,
        }
        context.audit_log.append(entry)

    async def _execute_tool_call_with_policy(
        self,
        context: RunContext,
        tool: Any,
        tool_id: Any,
        call: ToolCall,
        *,
        recipe: str | None = None,
        step: str | None = None,
        probe: bool = False,
    ) -> tuple[ToolResult, dict[str, Any], dict[str, Any]]:
        policy_cache_key = self._policy_cache_key(context, tool_id, tool, call.arguments)
        cached = context.policy_cache.get(policy_cache_key)
        if cached:
            risk = DesktopRisk(cached["risk"])
            paths_validated = self._mark_cached_paths(cached["paths_validated"])
            approval_required = cached["approval_required"]
            allowlist_match = cached["allowlist_match"]
            policy_cached = True
        else:
            risk = self._classify_risk(tool, call.arguments)
            paths_validated = self._validate_paths(context, tool, call.arguments)
            approval_required = self._requires_approval(risk, tool, call.arguments) or self._requires_path_override(
                context, tool, call.arguments
            )
            allowlist_match = self._allowlisted(tool, call.arguments)
            context.policy_cache[policy_cache_key] = {
                "risk": risk.value,
                "approval_required": approval_required,
                "allowlist_match": allowlist_match,
                "paths_validated": paths_validated,
            }
            policy_cached = False
        start_time = datetime.now().isoformat()
        approved, approval_reason, allowed_paths = await self._check_approval(
            context, risk, tool, call.arguments
        )
        policy_entry = {
            "event": "policy_check",
            "recipe": recipe,
            "step": step,
            "tool_id": getattr(tool_id, "qualified", tool.name),
            "risk": risk.value,
            "risk_level": getattr(tool, "risk_level", "unknown"),
            "mode": self.mode.value,
            "approval_required": approval_required,
            "approval_result": approved,
            "approval_reason": approval_reason,
            "paths_validated": paths_validated,
            "allowlist_match": allowlist_match,
            "denylist_match": False,
            "start_time": start_time,
            "end_time": None,
            "cached": policy_cached,
            "probe": probe,
        }
        context.audit_log.append(policy_entry)
        self.app.last_policy_trace = policy_entry
        if not approved:
            policy_entry["end_time"] = datetime.now().isoformat()
            return (
                ToolResult(success=False, content="", error=f"Approval denied ({approval_reason})."),
                {},
                policy_entry,
            )

        tool_result, audit = await self.app._run_tool(
            tool,
            call,
            tool_id,
            allowed_paths=allowed_paths,
        )
        self._record_tool_audit(
            context,
            tool,
            call,
            tool_result,
            audit,
            risk,
            approval_reason,
            probe=probe,
        )
        policy_entry["end_time"] = datetime.now().isoformat()
        return tool_result, audit, policy_entry

    async def _check_approval(
        self,
        context: RunContext,
        risk: DesktopRisk,
        tool: Any,
        args: dict[str, Any],
    ) -> tuple[bool, str, list[Path] | None]:
        approval_reason = "auto"
        allowed_paths = context.allowed_roots

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
            return not self._allowlisted(tool, args)
        if self.mode == DesktopOpsMode.GUIDE:
            if risk == DesktopRisk.EXEC_USERSPACE and self._allowlisted(tool, args):
                return False
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
        result = self._cached_path_validation(context, value)
        return not result.get("allowed", False)

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

    def _validate_paths(
        self,
        context: RunContext,
        tool: Any,
        args: dict[str, Any],
    ) -> dict[str, dict[str, Any]]:
        results: dict[str, dict[str, Any]] = {}
        for param in getattr(tool, "path_params", ()) or ():
            value = args.get(param)
            if not value:
                continue
            cached = self._cached_path_validation(context, value)
            results[param] = {**cached, "value": value}
        return results

    def _classify_risk(self, tool: Any, args: dict[str, Any]) -> DesktopRisk:
        desktop_risk = getattr(tool, "desktop_risk", None)
        if desktop_risk:
            return DesktopRisk(desktop_risk)
        if getattr(tool, "requires_network", False):
            return DesktopRisk.NETWORK
        if getattr(tool, "name", "") == "write_file":
            path = args.get("path")
            if path:
                try:
                    resolved = resolve_and_validate_path(
                        path,
                        workspace=self.app.workspace.current,
                        allowed_paths=self._allowed_roots(),
                        denied_paths=getattr(self.app.tool_policy, "denied_paths", None),
                    )
                    if resolved.exists() or args.get("mode") == "append":
                        return DesktopRisk.WRITE_DESTRUCTIVE
                    return DesktopRisk.WRITE_SAFE
                except FileToolError:
                    return DesktopRisk.WRITE_DESTRUCTIVE
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
        outcome = self._summary_outcome(status, summary)
        summary_text = SummaryBuilder(
            mode=context.mode.value,
            audit_entries=context.audit_log,
            artifacts=artifacts,
            artifact_registry=self.app.workspace.artifacts if self.app.workspace else None,
            outcome=outcome,
            summary_format=self.summary_format,
        ).build()
        self._update_desktop_status(context, recipe=None)
        return DesktopOpsResult(
            status=status,
            summary=summary_text,
            audit_log=context.audit_log,
            artifacts=artifacts,
            run_log_path=run_log_path,
        )

    def _write_audit_log(self, context: RunContext) -> Path | None:
        if not self.app.workspace.current:
            return None
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        artifact_dir = self.app.workspace.current.artifact_dir
        artifact_dir.mkdir(parents=True, exist_ok=True)
        path = artifact_dir / f"desktop_ops_{timestamp}.json"
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
        upper = content.upper()

        # Check for explicit completion markers
        if re.search(r"\b(DONE|COMPLETE|COMPLETED|FINISHED)\b", upper):
            return True

        # Check for completion phrases
        completion_phrases = [
            "TASK COMPLETE",
            "ALL DONE",
            "SUCCESSFULLY COMPLETED",
            "OPERATION SUCCESSFUL",
            "EXECUTION COMPLETE",
        ]
        for phrase in completion_phrases:
            if phrase in upper:
                return True

        return False

    def _task_appears_complete(self, context: RunContext, content: str) -> bool:
        """Detect if the task appears complete even without explicit DONE signal.

        Args:
            context: Current run context with audit log
            content: Assistant's response content

        Returns:
            True if task appears complete based on heuristics
        """
        if not content:
            return False

        # Only apply this heuristic if at least one tool was executed successfully
        successful_tools = [
            entry for entry in context.audit_log
            if entry.get("event") == "tool_call" and entry.get("success")
        ]
        if not successful_tools:
            return False

        lower_content = content.lower()

        # Check if model is asking what to do next (indicates current task is done)
        next_step_indicators = [
            "what would you like",
            "what do you want",
            "which folder would you like",
            "would you like me to",
            "should i",
            "what next",
            "anything else",
            "what else",
            "next steps",
            "what should i do next",
            "do you want me to",
        ]

        for indicator in next_step_indicators:
            if indicator in lower_content:
                # Model is asking for next task, current one appears done
                return True

        # Check if response indicates successful completion without explicit DONE
        success_indicators = [
            "successfully",
            "here's the",
            "here are the",
            "the following",
            "contains the following",
            "directory contains",
        ]

        # If we see success indicators AND the model is asking a question,
        # it likely completed the task and is asking what's next
        has_success_indicator = any(indicator in lower_content for indicator in success_indicators)
        ends_with_question = content.strip().endswith("?")

        if has_success_indicator and ends_with_question:
            return True

        return False

    def _extract_question(self, content: str) -> str | None:
        if not content:
            return None

        # Check for explicit question markers first
        markers = ("QUESTION:", "CLARIFY:", "NEED INPUT:")
        for marker in markers:
            if marker in content.upper():
                parts = content.split(":", 1)
                return parts[1].strip() if len(parts) > 1 else content

        # Check if content ends with a question mark (natural question detection)
        stripped = content.strip()
        if stripped.endswith("?"):
            # If the last sentence is a question, extract it
            sentences = stripped.split("\n")
            last_sentence = sentences[-1].strip()
            if last_sentence.endswith("?"):
                return last_sentence

        # Check for question patterns in the last few lines
        lines = stripped.split("\n")
        for line in reversed(lines[-3:]):  # Check last 3 lines
            line = line.strip()
            if line.endswith("?") or any(
                line.lower().startswith(prefix)
                for prefix in ("would you like", "do you want", "should i", "which", "what", "how")
            ):
                return line

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

    def _file_edit(self) -> FileEditPipeline:
        if self._file_edit_pipeline:
            return self._file_edit_pipeline
        workspace = self.app.workspace.current
        self._file_edit_pipeline = FileEditPipeline(
            workspace=workspace.root if workspace else None,
            allowed_paths=self._allowed_roots(),
            denied_paths=getattr(self.app.tool_policy, "denied_paths", None),
            artifact_dir=workspace.artifact_dir if workspace else None,
        )
        return self._file_edit_pipeline

    def _truncate_output(self, text: str, limit: int = 4000) -> tuple[str, bool]:
        if len(text) <= limit:
            return text, False
        return text[:limit] + "\n...[truncated]", True

    def _summarize_output(self, text: str, lines: int = 20) -> str:
        tail = "\n".join(text.splitlines()[-lines:])
        return f"(output truncated; last {lines} lines)\n{tail}"

    def _format_plan_output(
        self,
        context: RunContext,
        plan: Any | None,
        *,
        recipe_name: str | None,
        dry_run: bool = False,
    ) -> str:
        lines = ["Desktop Ops plan", f"Recipe: {recipe_name or 'manual plan'}"]
        if not plan:
            lines.append("Steps: (none)")
            return "\n".join(lines)
        lines.append("Steps:")
        steps = sorted(plan.steps, key=lambda item: (item.tool_name, item.name))
        for index, step in enumerate(steps, start=1):
            tool_id, tool, _ = self.app._resolve_tool_reference(step.tool_name)
            tool_label = getattr(tool_id, "qualified", step.tool_name)
            args = step.arguments(context, None) if callable(step.arguments) else step.arguments
            sanitized = self.app._sanitize_arguments(args)
            risk = self._classify_risk(tool, args) if tool else DesktopRisk.READ_ONLY
            approval_required = False
            paths = {}
            probe = False
            if tool:
                paths = self._validate_paths(context, tool, args)
                approval_required = self._requires_approval(risk, tool, args) or self._requires_path_override(
                    context, tool, args
                )
                if dry_run:
                    probe = self._should_probe(tool, args, risk)
            lines.append(
                f"  {index}. tool={tool_label} risk={risk.value} approval_required={'yes' if approval_required else 'no'}"
                + (f" probe={'true' if probe else 'false'}" if dry_run else "")
            )
            lines.append(
                "     args="
                + json.dumps(sanitized, ensure_ascii=False, sort_keys=True, default=str)
            )
            if paths:
                lines.append("     paths:")
                for param in sorted(paths):
                    entry = paths[param]
                    resolved = entry.get("resolved") or entry.get("value")
                    in_workspace = self._path_in_workspace(context, resolved)
                    allowed = "yes" if entry.get("allowed") else "no"
                    lines.append(
                        f"       - {param}: {resolved} (allowed={allowed}, in_workspace={in_workspace})"
                    )
            else:
                lines.append("     paths: (none)")
        return "\n".join(lines)

    async def _run_dry_run_probes(self, context: RunContext, plan: Any) -> None:
        for step in plan.steps:
            tool_id, tool, error = self.app._resolve_tool_reference(step.tool_name)
            if error or not tool:
                context.audit_log.append(
                    {
                        "event": "probe_skipped",
                        "step": step.name,
                        "reason": error or "tool_unavailable",
                    }
                )
                continue
            args = step.arguments(context, None) if callable(step.arguments) else step.arguments
            risk = self._classify_risk(tool, args)
            if not self._should_probe(tool, args, risk):
                context.audit_log.append(
                    {
                        "event": "probe_skipped",
                        "step": step.name,
                        "tool": getattr(tool_id, "qualified", tool.name),
                        "reason": "non_read_only",
                    }
                )
                continue
            tool_call = ToolCall(
                id=f"probe:{step.name}",
                name=getattr(tool_id, "qualified", tool.name),
                arguments=args,
            )
            await self._execute_tool_call_with_policy(
                context,
                tool,
                tool_id,
                tool_call,
                recipe="dry_run",
                step=step.name,
                probe=True,
            )

    def _should_probe(self, tool: Any, args: dict[str, Any], risk: DesktopRisk) -> bool:
        if risk == DesktopRisk.READ_ONLY:
            return True
        if risk in {DesktopRisk.EXEC_USERSPACE, DesktopRisk.EXEC_PRIVILEGED}:
            return self._is_safe_probe_command(tool, args)
        return False

    def _is_safe_probe_command(self, tool: Any, args: dict[str, Any]) -> bool:
        command = (args.get("command") or "").strip()
        if not command:
            return False
        safe_prefixes = ("pwd", "ls", "git status")
        if not any(command == prefix or command.startswith(prefix + " ") for prefix in safe_prefixes):
            return False
        return self._allowlisted(tool, args)

    def _path_in_workspace(self, context: RunContext, value: str | None) -> str:
        if not value or not self.app.workspace.current:
            return "unknown"
        try:
            resolved = Path(value).expanduser().resolve()
            workspace_root = self.app.workspace.current.root.expanduser().resolve()
            return "yes" if resolved.is_relative_to(workspace_root) else "no"
        except Exception:
            return "unknown"

    def _cached_path_validation(self, context: RunContext, value: str) -> dict[str, Any]:
        key = self._path_cache_key(context, value)
        cached = context.path_cache.get(key)
        if cached:
            return {**cached, "cached": True}
        try:
            resolved = resolve_and_validate_path(
                value,
                workspace=self.app.workspace.current,
                allowed_paths=self._allowed_roots(),
                denied_paths=getattr(self.app.tool_policy, "denied_paths", None),
            )
            result = {"resolved": str(resolved), "allowed": True, "cached": False}
        except Exception as exc:
            result = {"allowed": False, "error": str(exc), "cached": False}
        context.path_cache[key] = result
        return result

    def _path_cache_key(self, context: RunContext, value: str) -> str:
        allowed_roots = [str(path) for path in context.allowed_roots]
        try:
            resolved = str(Path(value).expanduser().resolve())
        except Exception:
            resolved = value
        payload = json.dumps({"path": resolved, "roots": allowed_roots}, sort_keys=True)
        return sha256(payload.encode("utf-8")).hexdigest()

    def _policy_cache_key(self, context: RunContext, tool_id: Any, tool: Any, args: dict[str, Any]) -> str:
        allowlist_version = self._stable_hash(self.config.auto_exec_allowlist)
        denylist = getattr(self.app.tool_policy, "denied_paths", None) or []
        denylist_version = self._stable_hash(denylist)
        allowed_roots_version = self._stable_hash([str(p) for p in context.allowed_roots])
        payload = {
            "tool": getattr(tool_id, "qualified", tool.name),
            "args": self._normalize_args(args),
            "mode": self.mode.value,
            "allowlist": allowlist_version,
            "denylist": denylist_version,
            "allowed_roots": allowed_roots_version,
        }
        return sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()

    @staticmethod
    def _normalize_args(args: dict[str, Any]) -> dict[str, Any]:
        def _normalize(value: Any) -> Any:
            if isinstance(value, dict):
                return {k: _normalize(v) for k, v in sorted(value.items())}
            if isinstance(value, list):
                return [_normalize(v) for v in value]
            return value

        return _normalize(args)

    @staticmethod
    def _stable_hash(values: Any) -> str:
        payload = json.dumps(values, sort_keys=True, default=str)
        return sha256(payload.encode("utf-8")).hexdigest()

    def _summary_outcome(self, status: str, reason: str) -> SummaryOutcome:
        if status == "completed":
            return SummaryOutcome(status="success")
        if status == "failed":
            return SummaryOutcome(status="blocked", reason=reason)
        return SummaryOutcome(status="partial", reason=reason)

    @staticmethod
    def _mark_cached_paths(paths: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
        return {key: {**value, "cached": True} for key, value in paths.items()}

    def _initialize_process_artifact(self, context: RunContext, handle: ProcessHandle) -> None:
        workspace = self.app.workspace.current
        if not workspace:
            return
        workspace.artifact_dir.mkdir(parents=True, exist_ok=True)
        safe_id = "".join(ch for ch in handle.process_id if ch.isalnum() or ch in {"-", "_"})
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = workspace.artifact_dir / f"process_{safe_id}_{timestamp}.log"
        path.write_text("", encoding="utf-8")
        handle.raw_output_path = path
        self.app.workspace.register_artifact_hint(
            {
                "path": str(path),
                "type": "log",
                "name": path.name,
                "description": "Process output log",
            },
            source="desktop_ops",
        )
        context.audit_log.append(
            {
                "event": "artifact",
                "artifact": {
                    "path": str(path),
                    "type": "log",
                    "name": path.name,
                    "description": "Process output log",
                },
            }
        )

    def _append_process_output(self, handle: ProcessHandle, output: str) -> None:
        if not handle.raw_output_path:
            return
        handle.raw_output_path.parent.mkdir(parents=True, exist_ok=True)
        with handle.raw_output_path.open("a", encoding="utf-8") as file:
            file.write(output)
            if not output.endswith("\n"):
                file.write("\n")

    def _condense_process_output(self, handle: ProcessHandle, output: str) -> str:
        condenser = handle.output_condenser or OutputCondenser()
        handle.output_condenser = condenser
        return condenser.condense(output)

    def _update_desktop_status(self, context: RunContext, *, recipe: str | None) -> None:
        if not hasattr(self.app, "desktop_ops_state"):
            return
        if recipe is not None:
            self.app.desktop_ops_state["recipe"] = recipe
        self.app.desktop_ops_state["cwd"] = str(context.cwd)
        self.app.desktop_ops_state["active_processes"] = len(context.active_processes)


class OutputCondenser:
    """Condense streaming output for display while keeping raw logs."""

    def __init__(self, *, max_bytes: int = 2000, max_lines: int = 20) -> None:
        self.max_bytes = max_bytes
        self.max_lines = max_lines
        self._last_chunk: str | None = None

    def condense(self, output: str) -> str:
        if not output:
            return ""
        if self._contains_error(output):
            self._last_chunk = output
            return output
        if output == self._last_chunk:
            return "[no new output]"
        self._last_chunk = output

        lines = output.splitlines()
        filtered_lines = [line for line in lines if line.strip()]
        if filtered_lines and all(self._is_progress_line(line) for line in filtered_lines):
            return "[progress output]"

        condensed = output
        if len(lines) > self.max_lines:
            condensed = "\n".join(lines[: self.max_lines])
            condensed += f"\n...[truncated {len(lines) - self.max_lines} lines]"
        if len(condensed) > self.max_bytes:
            condensed = condensed[: self.max_bytes] + "\n...[truncated]"
        return condensed

    @staticmethod
    def _contains_error(output: str) -> bool:
        lowered = output.lower()
        return any(token in lowered for token in ("error", "failed", "exception", "traceback"))

    @staticmethod
    def _is_progress_line(line: str) -> bool:
        stripped = line.strip()
        if not stripped:
            return False
        spinner_chars = set("|/-\\⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏")
        if len(stripped) <= 6 and all(char in spinner_chars for char in stripped):
            return True
        if "%" in stripped and any(ch in stripped for ch in ("█", "=", "-", ">")):
            return True
        return False
