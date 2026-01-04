"""Deterministic Desktop Ops run summaries."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
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
        summary_format: str = "text",
    ) -> None:
        self.mode = mode
        self.audit_entries = list(audit_entries)
        self.artifacts = list(artifacts or [])
        self.artifact_registry = artifact_registry
        self.outcome = outcome
        self.summary_format = summary_format

    def build(self) -> str:
        if self.summary_format == "json":
            return self._build_json()
        if self.summary_format == "markdown":
            return self._build_markdown()
        sections: list[str] = []
        sections.append(self._section_outcome())
        sections.append(self._section_work_performed())
        sections.append(self._section_approvals())
        sections.append(self._section_run_stats())
        sections.append(self._section_artifacts())
        next_actions = self._section_next_actions()
        if next_actions:
            sections.append(next_actions)
        return "\n\n".join(section for section in sections if section)

    def _build_markdown(self) -> str:
        sections: list[str] = []
        sections.append(self._section_outcome_markdown())
        sections.append(self._section_work_performed_markdown())
        sections.append(self._section_approvals_markdown())
        sections.append(self._section_run_stats_markdown())
        sections.append(self._section_artifacts_markdown())
        next_actions = self._section_next_actions_markdown()
        if next_actions:
            sections.append(next_actions)
        return "\n\n".join(section for section in sections if section)

    def _build_json(self) -> str:
        payload = {
            "outcome": {
                "status": self.outcome.status,
                "reason": self.outcome.reason,
            },
            "work_performed": {
                "recipe": self._recipe_used() or "manual plan",
                "commands": self._commands_executed(),
                "files_changed": self._files_changed(),
            },
            "approvals": self._meaningful_approvals(),
            "run_stats": self._run_stats(),
            "artifacts": self._collect_artifacts(),
            "next_actions": self._next_actions() if self.outcome.status.lower() != "success" else [],
        }
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)

    def _section_outcome(self) -> str:
        lines = ["Outcome"]
        if self.outcome.status.lower() == "success":
            lines.append("- Success")
        else:
            reason = f" - {self.outcome.reason}" if self.outcome.reason else ""
            lines.append(f"- {self.outcome.status.title()}{reason}")
        return "\n".join(lines)

    def _section_outcome_markdown(self) -> str:
        lines = ["## Outcome"]
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

    def _section_work_performed_markdown(self) -> str:
        lines = ["## Work performed"]
        recipe = self._recipe_used()
        lines.append(f"- **Recipe used**: {recipe or 'manual plan'}")

        commands = self._commands_executed()
        lines.append("- **Commands executed**:")
        if commands:
            lines.extend([f"  {idx}. `{command}`" for idx, command in enumerate(commands, start=1)])
        else:
            lines.append("  (none)")

        files = self._files_changed()
        if files:
            lines.append(f"- **Files changed** ({len(files)}):")
            lines.extend([f"  - `{path}`" for path in files])
        else:
            lines.append("- **Files changed**: (unknown)")
        return "\n".join(lines)

    def _section_approvals(self) -> str:
        lines = ["Approvals"]
        approvals = self._meaningful_approvals()
        if not approvals:
            lines.append("- None")
            return "\n".join(lines)
        lines.extend([f"- {entry}" for entry in approvals])
        return "\n".join(lines)

    def _section_approvals_markdown(self) -> str:
        lines = ["## Approvals"]
        approvals = self._meaningful_approvals()
        if not approvals:
            lines.append("- None")
            return "\n".join(lines)
        lines.extend([f"- {entry}" for entry in approvals])
        return "\n".join(lines)

    def _section_run_stats(self) -> str:
        stats = self._run_stats()
        lines = ["Run stats"]
        lines.append(f"- Steps executed: {stats['steps_executed']}")
        lines.append(
            f"- Policy cache hits/misses: {stats['policy_cache_hits']}/{stats['policy_cache_misses']}"
        )
        lines.append(
            f"- Path cache hits/misses: {stats['path_cache_hits']}/{stats['path_cache_misses']}"
        )
        lines.append(f"- Output condensed count: {stats['output_condensed_count']}")
        lines.append(f"- Probe steps count: {stats['probe_steps']}")
        return "\n".join(lines)

    def _section_run_stats_markdown(self) -> str:
        stats = self._run_stats()
        lines = ["## Run stats"]
        lines.append(f"- **Steps executed**: {stats['steps_executed']}")
        lines.append(
            f"- **Policy cache hits/misses**: {stats['policy_cache_hits']}/{stats['policy_cache_misses']}"
        )
        lines.append(
            f"- **Path cache hits/misses**: {stats['path_cache_hits']}/{stats['path_cache_misses']}"
        )
        lines.append(f"- **Output condensed count**: {stats['output_condensed_count']}")
        lines.append(f"- **Probe steps count**: {stats['probe_steps']}")
        return "\n".join(lines)

    def _section_artifacts(self) -> str:
        lines = ["Artifacts"]
        artifacts = self._collect_artifacts()
        if not any(artifacts.values()):
            lines.append("- None")
            return "\n".join(lines)
        for label in ("logs", "diffs", "files"):
            values = artifacts.get(label) or []
            if not values:
                continue
            lines.append(f"- {label.title()}:")
            lines.extend([f"  - {path}" for path in values])
        return "\n".join(lines)

    def _section_artifacts_markdown(self) -> str:
        lines = ["## Artifacts"]
        artifacts = self._collect_artifacts()
        if not any(artifacts.values()):
            lines.append("- None")
            return "\n".join(lines)
        for label in ("logs", "diffs", "files"):
            values = artifacts.get(label) or []
            if not values:
                continue
            lines.append(f"- **{label.title()}**:")
            lines.extend([f"  - `{path}`" for path in values])
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

    def _section_next_actions_markdown(self) -> str:
        if self.outcome.status.lower() == "success":
            return ""
        actions = self._next_actions()
        if not actions:
            return ""
        lines = ["## Next actions"]
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

    def _collect_artifacts(self) -> dict[str, list[str]]:
        seen: set[tuple[str, str]] = set()
        grouped: dict[str, list[str]] = {"logs": [], "diffs": [], "files": []}

        def _normalize_type(value: str | None) -> str | None:
            if not value:
                return None
            normalized = value.lower()
            if normalized in {"log", "logs"}:
                return "logs"
            if normalized in {"diff", "diffs", "patch"}:
                return "diffs"
            if normalized in {"file", "files"}:
                return "files"
            return None

        def _display_path(path: str | None) -> str | None:
            if not path:
                return None
            if self.artifact_registry:
                try:
                    root = self.artifact_registry.artifact_root
                    path_obj = Path(path)
                    if path_obj.is_relative_to(root):
                        return str(path_obj.relative_to(root))
                except Exception:
                    return str(path)
            return str(path)

        def _add(path: str | None, artifact_type: str | None) -> None:
            normalized_type = _normalize_type(artifact_type)
            display_path = _display_path(path)
            if not normalized_type or not display_path:
                return
            key = (normalized_type, display_path)
            if key in seen:
                return
            seen.add(key)
            grouped[normalized_type].append(display_path)

        for artifact in self.artifacts:
            if not isinstance(artifact, dict):
                continue
            _add(artifact.get("path"), artifact.get("type") or artifact.get("name"))

        if self.artifact_registry:
            for record in self.artifact_registry.all():
                _add(record.get("path"), record.get("type") or record.get("name"))

        for key in grouped:
            grouped[key] = sorted(grouped[key])
        return grouped

    def _run_stats(self) -> dict[str, int]:
        tool_calls = [entry for entry in self.audit_entries if entry.get("event") == "tool_call"]
        policy_entries = [
            entry for entry in self.audit_entries if entry.get("event") == "policy_check"
        ]
        policy_cache_hits = sum(1 for entry in policy_entries if entry.get("cached"))
        policy_cache_misses = sum(1 for entry in policy_entries if not entry.get("cached"))
        path_cache_hits = 0
        path_cache_misses = 0
        for entry in policy_entries:
            paths_validated = entry.get("paths_validated") or {}
            for value in paths_validated.values():
                if value.get("cached"):
                    path_cache_hits += 1
                else:
                    path_cache_misses += 1
        condensed_count = sum(
            1
            for entry in self.audit_entries
            if entry.get("event") == "process_output" and entry.get("output") == "[no new output]"
        )
        probe_steps = sum(1 for entry in tool_calls if entry.get("probe"))
        return {
            "steps_executed": len(tool_calls),
            "policy_cache_hits": policy_cache_hits,
            "policy_cache_misses": policy_cache_misses,
            "path_cache_hits": path_cache_hits,
            "path_cache_misses": path_cache_misses,
            "output_condensed_count": condensed_count,
            "probe_steps": probe_steps,
        }

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
