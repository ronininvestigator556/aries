"""Deterministic Desktop Ops run summaries."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterable

from aries.core.workspace import ArtifactRegistry


@dataclass(frozen=True)
class SummaryOutcome:
    status: str
    reason: str | None = None


class SummaryBuilder:
    """Build operator-grade summaries from structured audit records."""

    def __init__(
        self,
        *,
        mode: str,
        audit_entries: Iterable[dict[str, Any]],
        artifacts: Iterable[dict[str, Any]] | None = None,
        artifact_registry: ArtifactRegistry | None = None,
        outcome: SummaryOutcome,
    ) -> None:
        self.mode = mode
        self.audit_entries = list(audit_entries)
        self.artifacts = list(artifacts or [])
        self.artifact_registry = artifact_registry
        self.outcome = outcome

    def build(self) -> str:
        sections: list[str] = []
        sections.append(self._section_outcome())
        sections.append(self._section_work_performed())
        sections.append(self._section_approvals())
        sections.append(self._section_artifacts())
        next_actions = self._section_next_actions()
        if next_actions:
            sections.append(next_actions)
        return "\n\n".join(section for section in sections if section)

    def _section_outcome(self) -> str:
        lines = ["Outcome"]
        if self.outcome.status.lower() == "success":
            lines.append("- Success")
        else:
            reason = f" - {self.outcome.reason}" if self.outcome.reason else ""
            lines.append(f"- {self.outcome.status.title()}{reason}")
        return "\n".join(lines)

    def _section_work_performed(self) -> str:
        lines = ["Work performed"]
        recipe = self._recipe_used()
        lines.append(f"- Recipe used: {recipe or 'manual plan'}")

        commands = self._commands_executed()
        lines.append("- Commands executed:")
        if commands:
            lines.extend([f"  {idx}. {command}" for idx, command in enumerate(commands, start=1)])
        else:
            lines.append("  (none)")

        files = self._files_changed()
        if files:
            lines.append(f"- Files changed ({len(files)}):")
            lines.extend([f"  - {path}" for path in files])
        else:
            lines.append("- Files changed: (unknown)")
        return "\n".join(lines)

    def _section_approvals(self) -> str:
        lines = ["Approvals"]
        approvals = self._meaningful_approvals()
        if not approvals:
            lines.append("- None")
            return "\n".join(lines)
        lines.extend([f"- {entry}" for entry in approvals])
        return "\n".join(lines)

    def _section_artifacts(self) -> str:
        lines = ["Artifacts"]
        artifacts = self._collect_artifacts()
        if not artifacts:
            lines.append("- None")
            return "\n".join(lines)
        lines.extend([f"- {artifact}" for artifact in artifacts])
        return "\n".join(lines)

    def _section_next_actions(self) -> str:
        if self.outcome.status.lower() == "success":
            return ""
        actions = self._next_actions()
        if not actions:
            return ""
        lines = ["Next actions"]
        lines.extend([f"- {action}" for action in actions])
        return "\n".join(lines)

    def _recipe_used(self) -> str | None:
        for entry in self.audit_entries:
            if entry.get("event") == "recipe_plan":
                return entry.get("recipe")
        for entry in self.audit_entries:
            if entry.get("event") == "recipe_preference":
                return entry.get("recipe")
        return None

    def _commands_executed(self) -> list[str]:
        commands: list[str] = []
        for entry in self.audit_entries:
            if entry.get("event") != "tool_call":
                continue
            tool = entry.get("tool") or "<unknown>"
            audit = entry.get("audit") or {}
            args = audit.get("input") or {}
            if args:
                commands.append(f"{tool} {self._format_args(args)}")
            else:
                commands.append(f"{tool}")
        return commands

    def _files_changed(self) -> list[str]:
        paths: set[str] = set()
        for artifact in self.artifacts:
            path = artifact.get("path") if isinstance(artifact, dict) else None
            if not path:
                continue
            if artifact.get("type") in {"diff", "file"}:
                paths.add(str(path))
        if self.artifact_registry:
            for record in self.artifact_registry.all():
                if record.get("type") in {"diff", "file"}:
                    paths.add(str(record.get("path")))
        return sorted(paths)

    def _meaningful_approvals(self) -> list[str]:
        approvals: list[str] = []
        for entry in self.audit_entries:
            if entry.get("event") != "policy_check":
                continue
            risk = entry.get("risk")
            if risk not in {"WRITE_DESTRUCTIVE", "EXEC_PRIVILEGED", "NETWORK"}:
                continue
            if not entry.get("approval_required") or not entry.get("approval_result"):
                continue
            tool_id = entry.get("tool_id") or "<unknown>"
            reason = entry.get("approval_reason") or "auto"
            paths = self._format_paths(entry.get("paths_validated") or {})
            approvals.append(f"{tool_id} ({risk}) reason={reason}; paths={paths}")
        return approvals

    def _collect_artifacts(self) -> list[str]:
        seen: set[str] = set()
        artifacts: list[str] = []

        def _add(path: str | None, label: str | None) -> None:
            if not path or path in seen:
                return
            seen.add(path)
            if label:
                artifacts.append(f"{label}: {path}")
            else:
                artifacts.append(str(path))

        for artifact in self.artifacts:
            if not isinstance(artifact, dict):
                continue
            path = artifact.get("path")
            label = artifact.get("type") or artifact.get("name")
            _add(path, label)

        if self.artifact_registry:
            for record in self.artifact_registry.all():
                path = record.get("path")
                label = record.get("type") or record.get("name")
                _add(path, label)

        return sorted(artifacts)

    def _next_actions(self) -> list[str]:
        actions: list[str] = []
        denied = [
            entry
            for entry in self.audit_entries
            if entry.get("event") == "policy_check" and not entry.get("approval_result")
        ]
        if denied:
            entry = denied[0]
            tool_id = entry.get("tool_id") or "<unknown>"
            risk = entry.get("risk") or "unknown"
            actions.append(f"Approve or avoid {risk} for {tool_id} in the next run.")
        path_denied = [
            entry
            for entry in self.audit_entries
            if entry.get("event") == "path_override" and not entry.get("approved")
        ]
        if path_denied:
            actions.append("Move requested paths into the workspace or allow the override.")
        if not actions:
            actions.append("Review the last error in the audit log and retry with adjustments.")
        return actions[:3]

    @staticmethod
    def _format_args(args: dict[str, Any]) -> str:
        return json.dumps(args, ensure_ascii=False, sort_keys=True)

    def _format_paths(self, paths_validated: dict[str, dict[str, Any]]) -> str:
        if not paths_validated:
            return "none"
        parts: list[str] = []
        for key in sorted(paths_validated):
            entry = paths_validated[key]
            resolved = entry.get("resolved") or entry.get("value") or ""
            parts.append(str(resolved))
        return ", ".join(parts)
