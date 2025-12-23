"""
/run command - Agent Runs v1: stepwise, inspectable agent execution loop.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from datetime import datetime
from typing import TYPE_CHECKING

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from aries.commands.base import BaseCommand
from aries.core.agent_run import AgentRun, ApprovalDecision, PlanStep, RunStatus, StepResult, StepStatus
from aries.core.cancellation import CancellationToken
from aries.core.message import ToolCall
from aries.core.plan_parser import parse_plan
from aries.core.run_manager import RunManager
from aries.core.tool_tier import effective_tier, tool_to_tier
from aries.ui.display import display_error, display_info, display_success, display_warning
from aries.ui.input import get_user_input

if TYPE_CHECKING:
    from aries.cli import Aries

console = Console()


class RunCommand(BaseCommand):
    """Agent run management command."""

    name = "run"
    description = "Start and manage agent runs"
    usage = "<goal> | pause | resume | stop | status | steps | skip <n> | retry <n> | edit | inspect [run_id] | next | continue | archive [run_id]"

    async def execute(self, app: "Aries", args: str) -> None:
        """Execute run command."""
        args = args.strip()

        if not args:
            display_error("Usage: /run <goal> | pause | resume | stop | status | steps | skip <n> | retry <n> | edit | inspect [run_id] | next | continue | archive [run_id]")
            return

        # Initialize run manager if not already done
        if not hasattr(app, "run_manager"):
            workspace_root = app.workspace.current.root if app.workspace.current else None
            app.run_manager = RunManager(workspace_root)

        # Initialize current_run if not exists
        if not hasattr(app, "current_run") or app.current_run is None:
            app.current_run = None

        # Handle subcommands
        if args == "pause":
            await self._handle_pause(app)
        elif args == "resume":
            await self._handle_resume(app)
        elif args.startswith("resume "):
            run_id = args.split(maxsplit=1)[1]
            await self._handle_resume_by_id(app, run_id)
        elif args == "stop":
            await self._handle_stop(app)
        elif args == "status":
            await self._handle_status(app)
        elif args == "steps":
            await self._handle_steps(app)
        elif args.startswith("skip "):
            step_num = args.split(maxsplit=1)[1]
            try:
                await self._handle_skip(app, int(step_num))
            except ValueError:
                display_error(f"Invalid step number: {step_num}")
        elif args.startswith("retry "):
            step_num = args.split(maxsplit=1)[1]
            try:
                await self._handle_retry(app, int(step_num))
            except ValueError:
                display_error(f"Invalid step number: {step_num}")
        elif args == "edit":
            await self._handle_edit(app)
        elif args == "inspect" or args.startswith("inspect "):
            run_id = args.split(maxsplit=1)[1] if " " in args else None
            await self._handle_inspect(app, run_id)
        elif args == "next":
            await self._handle_next(app)
        elif args == "continue":
            await self._handle_continue(app)
        elif args.startswith("archive "):
            run_id = args.split(maxsplit=1)[1]
            await self._handle_archive(app, run_id)
        elif args == "archive":
            if app.current_run:
                await self._handle_archive(app, app.current_run.run_id)
            else:
                display_error("No active run to archive.")
        else:
            # Start new run with goal
            await self._handle_start(app, args)

    async def _handle_start(self, app: "Aries", goal: str) -> None:
        """Start a new agent run."""
        if app.current_run and app.current_run.status in (RunStatus.RUNNING, RunStatus.PLANNING):
            display_error(f"Run {app.current_run.run_id} is already in progress. Use /run stop first.")
            return

        if not app.workspace.current:
            display_error("No workspace open. Use /workspace open <name> first.")
            return

        # Create new run
        run_id = f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        app.current_run = AgentRun(
            run_id=run_id,
            goal=goal,
            status=RunStatus.PLANNING,
            model=app.current_model,
            profile=app.current_prompt or "default",
            workspace_name=app.workspace.current.name,
            cancellation_token=CancellationToken(),
            manual_stepping=False,
            archived=False,
        )
        app.current_run.started_at = datetime.now()

        # Update run manager workspace
        app.run_manager.workspace_root = app.workspace.current.root
        app.run_manager._ensure_runs_dir()

        display_info(f"Starting agent run: {run_id}")
        display_info(f"Goal: {goal}")

        # Generate plan
        app.current_run.status = RunStatus.PLANNING
        app.run_manager.save_run(app.current_run)

        plan = await self._generate_plan(app, goal)
        if not plan:
            app.current_run.status = RunStatus.FAILED
            app.current_run.completed_at = datetime.now()
            app.run_manager.save_run(app.current_run)
            display_error("Failed to generate plan.")
            return

        app.current_run.plan = plan
        app.current_run.status = RunStatus.RUNNING
        app.run_manager.save_run(app.current_run)

        # Display plan
        console.print("\n[bold]Plan:[/bold]")
        for step in plan:
            console.print(f"  {step.step_index + 1}. {step.title} (Tier {step.risk_tier})")

        # Execute run
        await self._execute_run(app)

    async def _generate_plan(self, app: "Aries", goal: str) -> list:
        """Generate plan using LLM."""
        prompt = f"""Generate a step-by-step plan to achieve this goal: {goal}

The plan should be structured as a JSON array of step objects. Each step should have:
- title: Short descriptive title
- intent: What this step aims to accomplish
- risk_tier: 0 (read-only/local), 1 (local writes), 2 (desktop control), 3 (network/browser)
- suggested_tools: Optional list of tool names that might be useful
- inputs_needed: Optional list of inputs required
- success_criteria: Optional description of what success looks like

Return ONLY a JSON array, no markdown or extra text.

Example format:
[
  {{"title": "Read configuration", "intent": "Load config file", "risk_tier": 0, "suggested_tools": ["read_file"]}},
  {{"title": "Process data", "intent": "Transform data", "risk_tier": 1, "suggested_tools": ["write_file"]}}
]"""

        try:
            messages = [
                {"role": "system", "content": app.conversation.system_prompt or "You are a helpful assistant."},
                {"role": "user", "content": prompt},
            ]

            response = await app.ollama.chat(
                model=app.current_model,
                messages=messages,
                raw=True,
            )

            content = response.get("message", {}).get("content", "") if isinstance(response, dict) else str(response)
            plan = parse_plan(content)

            if not plan:
                display_warning("Could not parse plan. Using fallback single-step plan.")
                plan = [
                    PlanStep(
                        title=goal,
                        intent=goal,
                        risk_tier=0,
                        suggested_tools=[],
                        inputs_needed=[],
                        success_criteria=None,
                        step_index=0,
                    )
                ]

            return plan

        except Exception as e:
            display_error(f"Error generating plan: {e}")
            return []

    async def _execute_run(self, app: "Aries") -> None:
        """Execute the agent run step by step."""
        run = app.current_run
        if not run:
            return

        try:
            while run.current_step_index < len(run.plan):
                if run.cancellation_token and run.cancellation_token.is_cancelled:
                    run.status = RunStatus.CANCELLED
                    break

                if run.status == RunStatus.PAUSED:
                    # Check if manual stepping mode
                    if hasattr(run, "manual_stepping") and run.manual_stepping:
                        display_info("Run is paused in manual stepping mode. Use /run next to execute next step or /run continue for automatic execution.")
                    else:
                        display_info("Run is paused. Use /run resume to continue.")
                    break

                step = run.plan[run.current_step_index]

                # Check approval for tier 2+ (step-level check)
                if step.risk_tier >= 2:
                    if not run.is_approved_for_tier(step.risk_tier):
                        run.status = RunStatus.AWAITING_APPROVAL
                        app.run_manager.save_run(run)

                        approved, scope = await self._request_approval(
                            app, step.risk_tier,
                            step_tier=step.risk_tier,
                            escalation_reason=f"Step requires Tier {step.risk_tier} actions",
                        )
                        if not approved:
                            run.status = RunStatus.STOPPED
                            break

                        decision = ApprovalDecision(
                            tier=step.risk_tier,
                            approved=True,
                            scope=scope,
                        )
                        run.approvals[step.risk_tier] = decision
                        run.status = RunStatus.RUNNING
                        app.run_manager.save_run(run)

                # Check tier 1 approval (workspace writes)
                if step.risk_tier == 1:
                    if 1 not in run.approvals:
                        # Prompt once for workspace writes
                        response = await get_user_input("Allow workspace writes for this run? [y/N]: ")
                        if response.strip().lower() in {"y", "yes"}:
                            run.approvals[1] = ApprovalDecision(tier=1, approved=True, scope="session")
                        else:
                            run.approvals[1] = ApprovalDecision(tier=1, approved=False, scope="denied")
                        app.run_manager.save_run(run)

                # Execute step
                result = await self._execute_step(app, step, run.current_step_index, run)
                run.set_step_result(result)
                app.run_manager.save_run(run)

                # Update status based on result
                if result.status == StepStatus.FAILED:
                    display_warning(f"Step {run.current_step_index + 1} failed: {result.error}")
                    # Continue to next step (operator can retry later)
                elif result.status == StepStatus.CANCELLED:
                    run.status = RunStatus.CANCELLED
                    break

                # Move to next step
                run.current_step_index += 1
                app.run_manager.save_run(run)

            # Run completed
            if run.status == RunStatus.RUNNING:
                run.status = RunStatus.COMPLETED
            run.completed_at = datetime.now()
            app.run_manager.save_run(run)

            # Generate report
            await self._finalize_run(app, run)

        except Exception as e:
            display_error(f"Run execution error: {e}")
            if run:
                run.status = RunStatus.FAILED
                run.completed_at = datetime.now()
                app.run_manager.save_run(run)
                await self._finalize_run(app, run)

    async def _execute_step(self, app: "Aries", step: PlanStep, step_index: int, run: AgentRun) -> StepResult:
        """Execute a single step."""
        result = StepResult(
            step_index=step_index,
            status=StepStatus.RUNNING,
            summary="",
        )
        result.started_at = datetime.now()

        console.print(f"\n[bold cyan]Step {step_index + 1}: {step.title}[/bold cyan]")
        console.print(f"[dim]Intent: {step.intent}[/dim]")
        if step.suggested_tools:
            console.print(f"[dim]Tools: {', '.join(step.suggested_tools)}[/dim]")

        try:
            # Ask LLM to execute step using tool calls
            prompt = f"""Execute step {step_index + 1} of the plan: "{step.title}"

Intent: {step.intent}

Use the available tools to accomplish this step. Call the appropriate tools to perform the required actions."""

            messages = [
                {"role": "system", "content": app.conversation.system_prompt or "You are a helpful assistant."},
                {"role": "user", "content": prompt},
            ]

            response = await app.ollama.chat(
                model=app.current_model,
                messages=messages,
                tools=app.tool_definitions or None,
                raw=True,
            )

            message_payload = response.get("message", {}) if isinstance(response, dict) else {}
            tool_calls_raw = message_payload.get("tool_calls") or []

            tool_calls_executed = []
            artifacts_collected = []

            if tool_calls_raw:
                tool_calls = app.conversation.parse_tool_calls(tool_calls_raw)
                for call in tool_calls:
                    tool_id, tool, error = app._resolve_tool_reference(call.name)
                    if error or tool is None:
                        result.status = StepStatus.FAILED
                        result.error = error or f"Unknown tool: {call.name}"
                        break

                    # Check tool-tier enforcement
                    workspace_root = app.workspace.current.root if app.workspace.current else None
                    tool_tier = tool_to_tier(tool, workspace_root)
                    effective = effective_tier(step.risk_tier, tool_tier)

                    # Check approval for effective tier
                    if effective >= 2:
                        if not run.is_approved_for_tier(effective):
                            run.status = RunStatus.AWAITING_APPROVAL
                            app.run_manager.save_run(run)

                            # C.2 - Tool Intent Disclosure
                            tool_provider = getattr(tool, "provider_id", "")
                            if tool_provider.startswith("mcp_"):
                                tool_provider = f"MCP {tool_provider.replace('mcp_', '').replace('_', ' ').title()}"
                            elif tool_provider:
                                tool_provider = tool_provider.replace("_", " ").title()
                            
                            escalation_reason = None
                            if tool_tier > step.risk_tier:
                                escalation_reason = f"Tool tier ({tool_tier}) exceeds step tier ({step.risk_tier})"
                            elif step.risk_tier >= 2:
                                escalation_reason = "Step requires high-tier actions"

                            approved, scope = await self._request_approval(
                                app, effective,
                                step_tier=step.risk_tier,
                                tool_tier=tool_tier,
                                tool_name=str(tool_id) if tool_id else tool.name,
                                tool_provider=tool_provider,
                                escalation_reason=escalation_reason,
                            )
                            if not approved:
                                result.status = StepStatus.FAILED
                                result.error = f"Tier {effective} actions not approved"
                                run.status = RunStatus.STOPPED
                                break

                            decision = ApprovalDecision(
                                tier=effective,
                                approved=True,
                                scope=scope,
                            )
                            run.approvals[effective] = decision
                            run.status = RunStatus.RUNNING
                            app.run_manager.save_run(run)

                        # Consume "once" approval after use
                        if run.approvals.get(effective) and run.approvals[effective].scope == "once":
                            run.consume_once_approval(effective)
                            app.run_manager.save_run(run)

                    # Execute tool
                    import time
                    tool_start = time.time()
                    tool_result, audit = await app._run_tool(tool, call, tool_id)
                    tool_latency_ms = int((time.time() - tool_start) * 1000)

                    # C.7 - MCP Visibility: Capture provider and latency
                    args_hash = hashlib.sha256(json.dumps(call.arguments, sort_keys=True).encode()).hexdigest()[:16]
                    tool_call_record = {
                        "tool_id": str(tool_id) if tool_id else call.name,
                        "args_hash": args_hash,
                        "provider": getattr(tool, "provider_id", ""),
                        "latency_ms": tool_latency_ms,
                    }
                    
                    if not tool_result.success:
                        tool_call_record["failure_reason"] = tool_result.error or "Unknown error"
                    
                    tool_calls_executed.append(tool_call_record)

                    # Collect artifacts
                    if tool_result.artifacts:
                        artifacts_collected.extend(tool_result.artifacts)
                    elif tool_result.metadata and tool_result.metadata.get("artifact"):
                        artifacts_collected.append(tool_result.metadata["artifact"])

                    if not tool_result.success:
                        result.status = StepStatus.FAILED
                        result.error = tool_result.error or "Tool execution failed"
                        break
            else:
                # No tool calls - step may be informational only
                content = message_payload.get("content", "")
                if not content.strip():
                    result.status = StepStatus.FAILED
                    result.error = "No tool calls or content generated"

            # Generate summary
            summary_prompt = f"""Summarize what happened in step "{step.title}" in 1-2 sentences.
            
Tool calls made: {len(tool_calls_executed)}
Artifacts created: {len(artifacts_collected)}
"""

            summary_response = await app.ollama.chat(
                model=app.current_model,
                messages=[
                    {"role": "system", "content": "You are a helpful assistant."},
                    {"role": "user", "content": summary_prompt},
                ],
                raw=True,
            )

            summary_content = summary_response.get("message", {}).get("content", "") if isinstance(summary_response, dict) else str(summary_response)
            summary = summary_content.strip() or f"Executed step: {step.title}"

            result.status = StepStatus.COMPLETED if result.status == StepStatus.RUNNING else result.status
            result.summary = summary
            result.tool_calls = tool_calls_executed
            result.artifacts = artifacts_collected

        except Exception as e:
            result.status = StepStatus.FAILED
            result.error = str(e)
            result.summary = f"Step failed: {e}"

        result.completed_at = datetime.now()
        if result.started_at:
            result.duration_ms = int((result.completed_at - result.started_at).total_seconds() * 1000)

        # Display result
        status_icon = "✓" if result.status == StepStatus.COMPLETED else "✗" if result.status == StepStatus.FAILED else "⊘"
        console.print(f"[{status_icon}] {result.summary}")
        if result.artifacts:
            console.print(f"  Artifacts: {len(result.artifacts)}")

        return result

    async def _request_approval(
        self, app: "Aries", tier: int, step_tier: int | None = None, 
        tool_tier: int | None = None, tool_name: str | None = None,
        tool_provider: str | None = None, escalation_reason: str | None = None
    ) -> tuple[bool, str]:
        """Request approval for a risk tier with tool intent disclosure.
        
        Args:
            tier: Effective tier requiring approval
            step_tier: Original step tier
            tool_tier: Tool's risk tier
            tool_name: Name of the tool
            tool_provider: Provider of the tool (e.g., "MCP Desktop Commander")
            escalation_reason: Why approval is needed (step vs tool)
        
        Returns:
            Tuple of (approved: bool, scope: str).
        """
        tier_names = {
            2: "Desktop Commander actions (desktop control)",
            3: "Playwright or networked/browser automation",
        }
        tier_name = tier_names.get(tier, f"Tier {tier} actions")

        # C.2 - Tool Intent Disclosure
        console.print(f"\n[bold yellow]Approval Required[/bold yellow]")
        
        if step_tier is not None and tool_tier is not None:
            console.print(f"[dim]Step tier: {step_tier} ({'local write' if step_tier == 1 else 'read-only' if step_tier == 0 else tier_names.get(step_tier, 'unknown')})[/dim]")
            console.print(f"[dim]Tool tier: {tool_tier} ({tier_names.get(tool_tier, 'unknown')})[/dim]")
            console.print(f"[bold]Effective tier: {tier} (max of step and tool)[/bold]")
            
            if tool_name:
                provider_display = f" ({tool_provider})" if tool_provider else ""
                console.print(f"[dim]Tool: {tool_name}{provider_display}[/dim]")
            
            if escalation_reason:
                console.print(f"[dim]Reason: {escalation_reason}[/dim]")
        
        console.print(f"\nAllow {tier_name} for this run?")
        response = await get_user_input("(Allow once / Allow for session / Deny) [o/s/N]: ")

        response_lower = response.strip().lower()
        if response_lower in {"o", "once"}:
            return True, "once"
        if response_lower in {"s", "session"}:
            return True, "session"
        return False, "denied"

    async def _finalize_run(self, app: "Aries", run: AgentRun) -> None:
        """Finalize run and generate report."""
        if not app.workspace.current:
            return

        artifact_dir = app.workspace.current.artifact_dir
        report_path = app.run_manager.save_run_report(run, artifact_dir)

        # Register report as artifact
        if app.workspace.artifacts:
            app.workspace.artifacts.register_file(
                report_path,
                description=f"Run report for {run.run_id}",
                source="agent_run",
            )

        display_success(f"Run {run.status.value}. Report saved: {report_path.name}")

    async def _handle_pause(self, app: "Aries") -> None:
        """Pause current run."""
        if not app.current_run:
            display_error("No active run.")
            return

        if app.current_run.status != RunStatus.RUNNING:
            display_error(f"Run is not running (status: {app.current_run.status.value})")
            return

        app.current_run.status = RunStatus.PAUSED
        app.run_manager.save_run(app.current_run)
        display_success("Run paused.")

    async def _handle_resume(self, app: "Aries") -> None:
        """Resume paused run."""
        if not app.current_run:
            display_error("No active run.")
            return

        if app.current_run.status != RunStatus.PAUSED:
            display_error(f"Run is not paused (status: {app.current_run.status.value})")
            return

        app.current_run.status = RunStatus.RUNNING
        app.run_manager.save_run(app.current_run)
        display_success("Resuming run...")
        await self._execute_run(app)

    async def _handle_stop(self, app: "Aries") -> None:
        """Stop current run."""
        if not app.current_run:
            display_error("No active run.")
            return

        if app.current_run.status in (RunStatus.COMPLETED, RunStatus.STOPPED, RunStatus.CANCELLED):
            display_error(f"Run is already {app.current_run.status.value}.")
            return

        if app.current_run.cancellation_token:
            app.current_run.cancellation_token.cancel()

        app.current_run.status = RunStatus.STOPPED
        app.current_run.completed_at = datetime.now()
        app.run_manager.save_run(app.current_run)

        await self._finalize_run(app, app.current_run)
        display_success("Run stopped.")

    async def _handle_status(self, app: "Aries") -> None:
        """Show run status."""
        if not app.current_run:
            display_info("No active run.")
            return

        run = app.current_run
        duration = run.duration_seconds()

        console.print(f"\n[bold]Run Status:[/bold] {run.status.value}")
        console.print(f"Run ID: {run.run_id}")
        console.print(f"Goal: {run.goal}")
        console.print(f"Started: {run.started_at.isoformat() if run.started_at else 'N/A'}")
        if duration:
            console.print(f"Duration: {duration:.1f}s")
        if run.current_step_index < len(run.plan):
            current_step = run.plan[run.current_step_index]
            console.print(f"Next step: {run.current_step_index + 1}. {current_step.title}")

    async def _handle_steps(self, app: "Aries") -> None:
        """Show plan steps with completion status."""
        if not app.current_run:
            display_info("No active run.")
            return

        run = app.current_run
        console.print(f"\n[bold]Plan Steps:[/bold]")
        for step in run.plan:
            result = run.get_step_result(step.step_index)
            if result:
                status_icon = {
                    StepStatus.COMPLETED: "✓",
                    StepStatus.FAILED: "✗",
                    StepStatus.SKIPPED: "⊘",
                    StepStatus.CANCELLED: "⊘",
                }.get(result.status, "○")
            elif step.step_index == run.current_step_index:
                status_icon = "→"
            else:
                status_icon = "○"

            console.print(f"  {status_icon} {step.step_index + 1}. {step.title} (Tier {step.risk_tier})")
            if result and result.summary:
                console.print(f"      {result.summary}")

    async def _handle_skip(self, app: "Aries", step_num: int) -> None:
        """Skip a step."""
        if not app.current_run:
            display_error("No active run.")
            return

        step_index = step_num - 1
        if step_index < 0 or step_index >= len(app.current_run.plan):
            display_error(f"Invalid step number: {step_num}")
            return

        result = StepResult(
            step_index=step_index,
            status=StepStatus.SKIPPED,
            summary="Step skipped by operator",
        )
        result.completed_at = datetime.now()

        app.current_run.set_step_result(result)
        
        # If skipping current step, advance pointer
        if app.current_run.current_step_index == step_index:
            app.current_run.current_step_index += 1
        
        app.run_manager.save_run(app.current_run)

        display_success(f"Step {step_num} skipped.")

    async def _handle_retry(self, app: "Aries", step_num: int) -> None:
        """Retry a step."""
        if not app.current_run:
            display_error("No active run.")
            return

        step_index = step_num - 1
        if step_index < 0 or step_index >= len(app.current_run.plan):
            display_error(f"Invalid step number: {step_num}")
            return

        step = app.current_run.plan[step_index]
        result = await self._execute_step(app, step, step_index, app.current_run)

        app.current_run.set_step_result(result)
        
        # Set current step to retried step if run is paused
        if app.current_run.status == RunStatus.PAUSED:
            app.current_run.current_step_index = step_index
        
        app.run_manager.save_run(app.current_run)

        display_success(f"Step {step_num} retried.")

    async def _handle_edit(self, app: "Aries") -> None:
        """Edit the plan."""
        if not app.current_run:
            display_error("No active run.")
            return

        if app.current_run.status == RunStatus.RUNNING:
            display_warning("Cannot edit plan while run is executing. Pause first.")
            return

        await self._edit_plan_interactive(app, app.current_run)

    async def _handle_inspect(self, app: "Aries", run_id: str | None) -> None:
        """Inspect a run (read-only)."""
        # Initialize run manager if needed
        if not hasattr(app, "run_manager"):
            workspace_root = app.workspace.current.root if app.workspace.current else None
            app.run_manager = RunManager(workspace_root)

        # Get run to inspect
        if run_id:
            run = app.run_manager.load_run(run_id)
            if not run:
                display_error(f"Run '{run_id}' not found.")
                return
        elif app.current_run:
            run = app.current_run
        else:
            display_error("No run specified and no active run.")
            return

        # Display run inspection
        await self._display_run_inspection(app, run)

    async def _handle_next(self, app: "Aries") -> None:
        """Execute next step then pause (manual stepping mode)."""
        if not app.current_run:
            display_error("No active run.")
            return

        if app.current_run.status not in (RunStatus.RUNNING, RunStatus.PAUSED):
            display_error(f"Run is not in a state that allows stepping (status: {app.current_run.status.value})")
            return

        # Set manual stepping mode
        if not hasattr(app.current_run, "manual_stepping"):
            app.current_run.manual_stepping = True
        else:
            app.current_run.manual_stepping = True

        app.current_run.status = RunStatus.RUNNING
        app.run_manager.save_run(app.current_run)

        # Execute one step
        if app.current_run.current_step_index < len(app.current_run.plan):
            step = app.current_run.plan[app.current_run.current_step_index]
            result = await self._execute_step(app, step, app.current_run.current_step_index, app.current_run)
            app.current_run.set_step_result(result)
            app.current_run.current_step_index += 1
            app.current_run.status = RunStatus.PAUSED
            app.run_manager.save_run(app.current_run)
            display_success("Step executed. Run paused. Use /run next to continue or /run continue for automatic execution.")
        else:
            app.current_run.status = RunStatus.COMPLETED
            app.current_run.completed_at = datetime.now()
            app.run_manager.save_run(app.current_run)
            await self._finalize_run(app, app.current_run)

    async def _handle_continue(self, app: "Aries") -> None:
        """Resume normal sequential execution (exit manual stepping mode)."""
        if not app.current_run:
            display_error("No active run.")
            return

        if hasattr(app.current_run, "manual_stepping"):
            app.current_run.manual_stepping = False

        if app.current_run.status == RunStatus.PAUSED:
            app.current_run.status = RunStatus.RUNNING
            app.run_manager.save_run(app.current_run)
            display_success("Resuming automatic execution...")
            await self._execute_run(app)
        else:
            display_error(f"Run is not paused (status: {app.current_run.status.value})")

    async def _handle_resume_by_id(self, app: "Aries", run_id: str) -> None:
        """Resume a specific run by ID."""
        if not hasattr(app, "run_manager"):
            workspace_root = app.workspace.current.root if app.workspace.current else None
            app.run_manager = RunManager(workspace_root)

        run = app.run_manager.load_run(run_id)
        if not run:
            display_error(f"Run '{run_id}' not found.")
            return

        if run.status != RunStatus.PAUSED:
            display_error(f"Run '{run_id}' is not paused (status: {run.status.value}). Only paused runs can be resumed.")
            return

        app.current_run = run
        app.current_run.status = RunStatus.RUNNING
        app.run_manager.save_run(app.current_run)
        display_success(f"Resuming run {run_id}...")
        await self._execute_run(app)

    async def _handle_archive(self, app: "Aries", run_id: str) -> None:
        """Archive a run (mark as non-resumable)."""
        if not hasattr(app, "run_manager"):
            workspace_root = app.workspace.current.root if app.workspace.current else None
            app.run_manager = RunManager(workspace_root)

        run = app.run_manager.load_run(run_id)
        if not run:
            display_error(f"Run '{run_id}' not found.")
            return

        # Mark as archived
        if not hasattr(run, "archived"):
            run.archived = True
        else:
            run.archived = True

        app.run_manager.save_run(run)
        display_success(f"Run {run_id} archived.")

    async def _display_run_inspection(self, app: "Aries", run: AgentRun) -> None:
        """Display detailed run inspection (read-only)."""
        # Metadata panel
        duration = run.duration_seconds()
        duration_str = f"{duration:.1f}s" if duration else "N/A"
        metadata_text = f"""Run ID: {run.run_id}
Goal: {run.goal}
Status: {run.status.value}
Started: {run.started_at.isoformat() if run.started_at else 'N/A'}
Completed: {run.completed_at.isoformat() if run.completed_at else 'N/A'}
Duration: {duration_str}
Model: {run.model}
Profile: {run.profile}
Workspace: {run.workspace_name or 'N/A'}"""

        metadata_panel = Panel(metadata_text, title="Run Metadata", border_style="cyan")
        console.print(metadata_panel)

        # Approvals panel
        if run.approvals:
            approvals_text = []
            for tier, decision in sorted(run.approvals.items()):
                status = "✓ Approved" if decision.approved else "✗ Denied"
                approvals_text.append(f"Tier {tier}: {status} ({decision.scope}) - {decision.timestamp.strftime('%Y-%m-%d %H:%M:%S')}")
            approvals_panel = Panel("\n".join(approvals_text), title="Approval Decisions", border_style="yellow")
            console.print(approvals_panel)
        else:
            approvals_panel = Panel("No approvals recorded", title="Approval Decisions", border_style="yellow")
            console.print(approvals_panel)

        # Plan panel
        plan_text = []
        for step in run.plan:
            result = run.get_step_result(step.step_index)
            if result:
                status_icon = {
                    StepStatus.COMPLETED: "✓",
                    StepStatus.FAILED: "✗",
                    StepStatus.SKIPPED: "⊘",
                    StepStatus.CANCELLED: "⊘",
                    StepStatus.PENDING: "○",
                    StepStatus.RUNNING: "→",
                }.get(result.status, "○")
                artifact_count = len(result.artifacts) if result.artifacts else 0
                plan_text.append(f"{status_icon} Step {step.step_index + 1}: {step.title} (Tier {step.risk_tier}) - {artifact_count} artifacts")
            elif step.step_index == run.current_step_index:
                plan_text.append(f"→ Step {step.step_index + 1}: {step.title} (Tier {step.risk_tier}) - Current")
            else:
                plan_text.append(f"○ Step {step.step_index + 1}: {step.title} (Tier {step.risk_tier}) - Pending")

        plan_panel = Panel("\n".join(plan_text), title="Plan Steps", border_style="green")
        console.print(plan_panel)

        # Step details
        if run.step_results:
            console.print("\n[bold]Step Execution Details:[/bold]")
            for step_index in sorted(run.step_results.keys()):
                result = run.step_results[step_index]
                step = next((s for s in run.plan if s.step_index == step_index), None)
                step_title = step.title if step else f"Step {step_index + 1}"

                details = f"""Step: {step_title}
Status: {result.status.value}
Summary: {result.summary}
Tool Calls: {len(result.tool_calls)}
Artifacts: {len(result.artifacts)}"""
                if result.error:
                    details += f"\nError: {result.error}"
                if result.duration_ms:
                    details += f"\nDuration: {result.duration_ms}ms"""

                step_panel = Panel(details, title=f"Step {step_index + 1}", border_style="blue")
                console.print(step_panel)

    async def _edit_plan_interactive(self, app: "Aries", run: AgentRun) -> None:
        """Interactive plan editing."""
        if run.status != RunStatus.PAUSED:
            display_error("Run must be paused to edit plan.")
            return

        console.print("\n[bold]Plan Editor[/bold]")
        console.print("Available commands:")
        console.print("  rename <n> <new_title> - Rename step n")
        console.print("  intent <n> <new_intent> - Edit step intent")
        console.print("  tier <n> <0-3> - Change step risk tier")
        console.print("  reorder <n> <new_position> - Move step to new position")
        console.print("  done - Finish editing")

        # Show current plan
        await self._handle_steps(app)

        # Simple editing loop
        while True:
            try:
                command = await get_user_input("\nEdit command (or 'done'): ")
                command = command.strip()

                if command == "done":
                    break

                parts = command.split()
                if len(parts) < 3:
                    display_error("Invalid command format.")
                    continue

                cmd = parts[0].lower()
                try:
                    step_num = int(parts[1])
                    step_index = step_num - 1
                except ValueError:
                    display_error(f"Invalid step number: {parts[1]}")
                    continue

                if step_index < 0 or step_index >= len(run.plan):
                    display_error(f"Step {step_num} does not exist.")
                    continue

                if cmd == "rename":
                    new_title = " ".join(parts[2:])
                    run.plan[step_index].title = new_title
                    # Invalidate downstream results
                    self._invalidate_downstream_results(run, step_index)
                    app.run_manager.save_run(run)
                    display_success(f"Step {step_num} renamed to: {new_title}")

                elif cmd == "intent":
                    new_intent = " ".join(parts[2:])
                    run.plan[step_index].intent = new_intent
                    app.run_manager.save_run(run)
                    display_success(f"Step {step_num} intent updated.")

                elif cmd == "tier":
                    try:
                        new_tier = int(parts[2])
                        if new_tier < 0 or new_tier > 3:
                            display_error("Risk tier must be 0-3")
                            continue
                        run.plan[step_index].risk_tier = new_tier
                        # Invalidate downstream results
                        self._invalidate_downstream_results(run, step_index)
                        app.run_manager.save_run(run)
                        display_success(f"Step {step_num} risk tier set to {new_tier}")
                    except ValueError:
                        display_error(f"Invalid tier: {parts[2]}")

                elif cmd == "reorder":
                    try:
                        new_position = int(parts[2])
                        new_index = new_position - 1
                        if new_index < 0 or new_index >= len(run.plan):
                            display_error(f"Invalid position: {new_position}")
                            continue

                        # Reorder step
                        step = run.plan.pop(step_index)
                        run.plan.insert(new_index, step)

                        # Reassign step indices
                        for idx, s in enumerate(run.plan):
                            s.step_index = idx

                        # Invalidate all results after the moved step
                        min_affected = min(step_index, new_index)
                        self._invalidate_downstream_results(run, min_affected)

                        app.run_manager.save_run(run)
                        display_success(f"Step {step_num} moved to position {new_position}")
                    except ValueError:
                        display_error(f"Invalid position: {parts[2]}")

                else:
                    display_error(f"Unknown command: {cmd}")

            except KeyboardInterrupt:
                display_info("\nEditing cancelled.")
                break

        # Record audit entry
        if not hasattr(run, "audit_log"):
            run.audit_log = []
        run.audit_log.append({
            "action": "plan_edited",
            "timestamp": datetime.now().isoformat(),
            "operator": "user",
        })
        app.run_manager.save_run(run)
        display_success("Plan editing complete.")

    def _invalidate_downstream_results(self, run: AgentRun, from_index: int) -> None:
        """Invalidate step results from a given index onwards."""
        to_remove = [idx for idx in run.step_results.keys() if idx >= from_index]
        for idx in to_remove:
            del run.step_results[idx]

