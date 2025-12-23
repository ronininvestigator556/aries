"""
Agent Run Manager - handles persistence and run report generation.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from aries.core.agent_run import AgentRun, RunStatus, StepStatus


class RunManager:
    """Manages agent run persistence and report generation."""

    def __init__(self, workspace_root: Path | None = None) -> None:
        """Initialize run manager.
        
        Args:
            workspace_root: Root directory of workspace. If None, runs are not persisted.
        """
        self.workspace_root = workspace_root
        self.runs_dir: Path | None = None
        if workspace_root:
            self._ensure_runs_dir()

    def _ensure_runs_dir(self) -> None:
        """Ensure runs directory exists."""
        if self.workspace_root:
            self.runs_dir = self.workspace_root / ".aries" / "runs"
            self.runs_dir.mkdir(parents=True, exist_ok=True)

    def save_run(self, run: AgentRun) -> None:
        """Save run metadata to disk.
        
        Args:
            run: AgentRun to save.
        """
        if not self.runs_dir:
            return

        run_file = self.runs_dir / f"{run.run_id}.json"
        run_file.write_text(json.dumps(run.to_dict(), indent=2), encoding="utf-8")

    def load_run(self, run_id: str) -> AgentRun | None:
        """Load run metadata from disk.
        
        Args:
            run_id: Run identifier.
            
        Returns:
            AgentRun if found, None otherwise.
        """
        if not self.runs_dir:
            return None

        run_file = self.runs_dir / f"{run_id}.json"
        if not run_file.exists():
            return None

        try:
            data = json.loads(run_file.read_text(encoding="utf-8"))
            return AgentRun.from_dict(data)
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.debug(f"Failed to load run {run_id}: {e}", exc_info=True)
            return None

    def list_runs(self) -> list[str]:
        """List all run IDs.
        
        Returns:
            List of run IDs.
        """
        if not self.runs_dir:
            return []

        return sorted([f.stem for f in self.runs_dir.glob("*.json")])

    def generate_run_report(
        self,
        run: AgentRun,
        artifact_dir: Path | None = None,
    ) -> tuple[str, dict[str, Any]]:
        """Generate run report as markdown and JSON.
        
        Args:
            run: AgentRun to generate report for.
            artifact_dir: Directory to save report artifacts.
            
        Returns:
            Tuple of (markdown_content, json_data).
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        duration = run.duration_seconds()

        # Build markdown report
        md_lines = [
            f"# Agent Run Report: {run.run_id}",
            "",
            "## Metadata",
            "",
            f"- **Run ID**: `{run.run_id}`",
            f"- **Goal**: {run.goal}",
            f"- **Status**: {run.status.value}",
            f"- **Started**: {run.started_at.isoformat() if run.started_at else 'N/A'}",
            f"- **Completed**: {run.completed_at.isoformat() if run.completed_at else 'N/A'}",
            f"- **Duration**: {duration:.1f}s" if duration else "- **Duration**: N/A",
            f"- **Model**: {run.model}",
            f"- **Profile**: {run.profile}",
            f"- **Workspace**: {run.workspace_name or 'N/A'}",
            "",
        ]

        # Approval decisions
        if run.approvals:
            md_lines.extend([
                "## Approval Decisions",
                "",
            ])
            for tier, decision in sorted(run.approvals.items()):
                md_lines.append(f"- **Tier {tier}**: {decision.scope} ({'approved' if decision.approved else 'denied'})")
            md_lines.append("")

        # Plan
        md_lines.extend([
            "## Plan",
            "",
        ])
        if run.plan:
            for step in run.plan:
                result = run.get_step_result(step.step_index)
                if result:
                    status_marker = {
                        StepStatus.COMPLETED: "✓",
                        StepStatus.FAILED: "✗",
                        StepStatus.SKIPPED: "⊘",
                        StepStatus.CANCELLED: "⊘",
                        StepStatus.PENDING: "○",
                        StepStatus.RUNNING: "→",
                    }.get(result.status, "○")
                elif step.step_index == run.current_step_index:
                    status_marker = "→"
                else:
                    status_marker = "○"
                
                md_lines.append(f"{status_marker} **Step {step.step_index + 1}**: {step.title}")
                md_lines.append(f"  - Intent: {step.intent}")
                md_lines.append(f"  - Risk Tier: {step.risk_tier}")
                if step.suggested_tools:
                    md_lines.append(f"  - Tools: {', '.join(step.suggested_tools)}")
                md_lines.append("")
        else:
            md_lines.append("No plan generated.")
            md_lines.append("")

        # Execution log
        md_lines.extend([
            "## Step-by-Step Execution Log",
            "",
        ])
        for result in run.step_results:
            step = next((s for s in run.plan if s.step_index == result.step_index), None)
            step_title = step.title if step else f"Step {result.step_index + 1}"

            status_icon = {
                StepStatus.COMPLETED: "✓",
                StepStatus.FAILED: "✗",
                StepStatus.SKIPPED: "⊘",
                StepStatus.CANCELLED: "⊘",
            }.get(result.status, "○")

            md_lines.append(f"### {status_icon} {step_title}")
            md_lines.append(f"- **Status**: {result.status.value}")
            md_lines.append(f"- **Summary**: {result.summary}")
            if result.started_at:
                md_lines.append(f"- **Started**: {result.started_at.isoformat()}")
            if result.completed_at:
                md_lines.append(f"- **Completed**: {result.completed_at.isoformat()}")
            if result.duration_ms:
                md_lines.append(f"- **Duration**: {result.duration_ms}ms")

            if result.tool_calls:
                md_lines.append("- **Tool Calls**:")
                for tool_call in result.tool_calls:
                    tool_id = tool_call.get("tool_id", tool_call.get("name", "unknown"))
                    args_hash = tool_call.get("args_hash", "")
                    provider = tool_call.get("provider", "")
                    latency_ms = tool_call.get("latency_ms")
                    failure_reason = tool_call.get("failure_reason")
                    
                    call_line = f"  - `{tool_id}`"
                    if provider:
                        call_line += f" ({provider})"
                    if latency_ms is not None:
                        call_line += f" [{latency_ms}ms]"
                    call_line += f" (args: {args_hash[:16]}...)"
                    if failure_reason:
                        call_line += f" [Failed: {failure_reason}]"
                    md_lines.append(call_line)

            if result.artifacts:
                md_lines.append("- **Artifacts**:")
                for artifact in result.artifacts:
                    artifact_id = artifact.get("id", artifact.get("path", "unknown"))
                    md_lines.append(f"  - `{artifact_id}`")

            if result.error:
                md_lines.append(f"- **Error**: {result.error}")

            md_lines.append("")

        # Errors and recoveries
        errors = [r for r in run.step_results if r.error]
        if errors:
            md_lines.extend([
                "## Errors and Recoveries",
                "",
            ])
            for result in errors:
                step = next((s for s in run.plan if s.step_index == result.step_index), None)
                step_title = step.title if step else f"Step {result.step_index + 1}"
                md_lines.append(f"### {step_title}")
                md_lines.append(f"**Error**: {result.error}")
                md_lines.append("")

        # Next suggested actions
        md_lines.extend([
            "## Next Suggested Actions",
            "",
        ])
        if run.status == RunStatus.COMPLETED:
            md_lines.append("Run completed successfully. Review artifacts and results.")
        elif run.status == RunStatus.FAILED:
            md_lines.append("Run failed. Review errors above and consider:")
            md_lines.append("- Retrying failed steps")
            md_lines.append("- Adjusting the plan")
            md_lines.append("- Checking tool permissions and workspace state")
        elif run.status == RunStatus.STOPPED:
            md_lines.append("Run was stopped. You can:")
            md_lines.append("- Resume from the current step")
            md_lines.append("- Edit the plan and continue")
            md_lines.append("- Start a new run with a refined goal")
        else:
            md_lines.append("Run is in progress or incomplete.")
        md_lines.append("")

        markdown_content = "\n".join(md_lines)

        # Build JSON data
        json_data = {
            "run_id": run.run_id,
            "goal": run.goal,
            "status": run.status.value,
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
            "duration_seconds": duration,
            "model": run.model,
            "profile": run.profile,
            "workspace_name": run.workspace_name,
            "approvals": {str(k): v.to_dict() for k, v in run.approvals.items()},
            "plan": [step.to_dict() for step in run.plan],
            "step_results": [result.to_dict() for result in run.step_results],
        }

        return markdown_content, json_data

    def save_run_report(
        self,
        run: AgentRun,
        artifact_dir: Path,
    ) -> Path:
        """Save run report to artifact directory.
        
        Args:
            run: AgentRun to generate report for.
            artifact_dir: Directory to save report.
            
        Returns:
            Path to saved markdown report.
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        markdown_content, json_data = self.generate_run_report(run, artifact_dir)

        # Save markdown
        md_path = artifact_dir / f"run_report_{timestamp}.md"
        md_path.write_text(markdown_content, encoding="utf-8")

        # Save JSON
        json_path = artifact_dir / f"run_report_{timestamp}.json"
        json_path.write_text(json.dumps(json_data, indent=2), encoding="utf-8")

        return md_path

