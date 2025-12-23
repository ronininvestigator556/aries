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
    usage = "<goal> | pause | resume | stop | status | steps | skip <n> | retry <n> | edit"

    async def execute(self, app: "Aries", args: str) -> None:
        """Execute run command."""
        args = args.strip()

        if not args:
            display_error("Usage: /run <goal> | pause | resume | stop | status | steps | skip <n> | retry <n> | edit")
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
                    display_info("Run is paused. Use /run resume to continue.")
                    break

                step = run.plan[run.current_step_index]

                # Check approval for tier 2+
                if step.risk_tier >= 2:
                    if not run.is_approved_for_tier(step.risk_tier):
                        run.status = RunStatus.AWAITING_APPROVAL
                        app.run_manager.save_run(run)

                        approved, scope = await self._request_approval(app, step.risk_tier)
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

                            approved, scope = await self._request_approval(app, effective)
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
                    tool_result, audit = await app._run_tool(tool, call, tool_id)
                    args_hash = hashlib.sha256(json.dumps(call.arguments, sort_keys=True).encode()).hexdigest()[:16]
                    tool_calls_executed.append({
                        "tool_id": str(tool_id) if tool_id else call.name,
                        "args_hash": args_hash,
                    })

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

    async def _request_approval(self, app: "Aries", tier: int) -> tuple[bool, str]:
        """Request approval for a risk tier.
        
        Returns:
            Tuple of (approved: bool, scope: str).
        """
        tier_names = {
            2: "Desktop Commander actions (desktop control)",
            3: "Playwright or networked/browser automation",
        }
        tier_name = tier_names.get(tier, f"Tier {tier} actions")

        console.print(f"\n[bold yellow]Approval Required[/bold yellow]")
        console.print(f"Allow {tier_name} for this run?")
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

        display_info("Plan editing not yet implemented. Use /run stop and start a new run with a refined goal.")

