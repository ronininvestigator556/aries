"""
/policy command - inspect tool policy status and dry-run decisions.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from rich.panel import Panel
from rich.table import Table

from aries.commands.base import BaseCommand
from aries.core.tool_policy import PolicyDecision
from aries.core.workspace import resolve_and_validate_path
from aries.ui.display import console, display_error

if TYPE_CHECKING:
    from aries.cli import Aries


class PolicyCommand(BaseCommand):
    """Inspect tool policy configuration and dry-run evaluations."""

    name = "policy"
    description = "Inspect tool policy status and dry-run tool evaluations"
    usage = "show | explain <tool> <json_args>"

    async def execute(self, app: "Aries", args: str) -> None:
        args = args.strip()
        if args.startswith("show") or not args:
            self._show_policy(app)
            return

        if args.startswith("explain"):
            payload = args.split(maxsplit=2)
            if len(payload) < 2:
                self._print_usage()
                return

            tool_name = payload[1]
            raw_json = payload[2] if len(payload) > 2 else "{}"
            try:
                parsed_args = json.loads(raw_json) if raw_json else {}
            except json.JSONDecodeError:
                display_error("Invalid JSON arguments.")
                self._print_usage()
                return

            if not isinstance(parsed_args, dict):
                display_error("Tool arguments must be a JSON object.")
                self._print_usage()
                return

            await self._explain(app, tool_name, parsed_args)
            return

        self._print_usage()

    def _print_usage(self) -> None:
        console.print(
            "\n[bold]/policy[/bold] commands:\n"
            "  /policy show\n"
            "  /policy explain <tool_name> <json_args>\n\n"
            "Example: /policy explain write_file {\"path\":\"notes.txt\",\"content\":\"hello\"}\n"
        )

    def _show_policy(self, app: "Aries") -> None:
        workspace = app.workspace.current
        workspace_label = "none"
        if workspace:
            workspace_label = f"{workspace.name} ({workspace.root})"

        token_active = getattr(app._token_estimator, "mode", None)
        token_configured = app.config.tokens.mode
        tokens_text = f"configured={token_configured}"
        if token_active:
            tokens_text += f", active={token_active}"

        confirmation_lines = [f"confirmation_required={app.config.tools.confirmation_required}"]
        exec_confirm = getattr(app.config.tools, "exec_always_confirm", None)
        if exec_confirm is not None:
            confirmation_lines.append(f"exec_always_confirm={exec_confirm}")

        allow_roots = self._collect_allowed_roots(app)
        deny_roots = [str(p) for p in getattr(app.tool_policy, "denied_paths", [])]

        allowlist = getattr(app.config.tools, "allowlist", None) or getattr(app.config.tools, "allowed_tools", None)
        denylist = getattr(app.config.tools, "denylist", None) or getattr(app.config.tools, "denied_tools", None)

        table = Table.grid(padding=(0, 1))
        table.add_row("Workspace:", workspace_label)
        table.add_row("Workspace root:", str(workspace.root) if workspace else "none")
        table.add_row("Tokens:", tokens_text)
        table.add_row("Tool enablement:", f"allow_shell={app.config.tools.allow_shell}, allow_network={app.config.tools.allow_network}")
        table.add_row("Confirmation:", "; ".join(confirmation_lines))
        table.add_row("Allowed roots:", ", ".join(allow_roots) if allow_roots else "none")
        table.add_row("Denied roots:", ", ".join(deny_roots) if deny_roots else "none")
        if allowlist:
            table.add_row("Tool allowlist:", ", ".join(allowlist))
        if denylist:
            table.add_row("Tool denylist:", ", ".join(denylist))

        console.print(Panel(table, title="Policy status", border_style="cyan"))

    def _collect_allowed_roots(self, app: "Aries") -> list[str]:
        roots: list[Path] = []
        if app.workspace.current:
            roots.append(app.workspace.current.root.expanduser().resolve())
        roots.extend(getattr(app.tool_policy, "allowed_paths", []))

        seen = set()
        ordered: list[str] = []
        for path in roots:
            resolved = str(Path(path).expanduser().resolve())
            if resolved in seen:
                continue
            seen.add(resolved)
            ordered.append(resolved)
        return ordered

    async def _explain(self, app: "Aries", tool_name: str, args: dict[str, Any]) -> None:
        tool = app.tool_map.get(tool_name)
        if tool is None:
            known = ", ".join(sorted(app.tool_map))
            display_error(f"Unknown tool: {tool_name}. Known tools: {known}")
            return

        workspace = app.workspace.current.root if app.workspace.current else None
        resolved_paths: dict[str, str] = {}
        path_errors: dict[str, str] = {}

        for param in getattr(tool, "path_params", ()):
            if param not in args:
                continue
            try:
                resolved = resolve_and_validate_path(
                    args[param],
                    workspace=workspace,
                    allowed_paths=getattr(app.tool_policy, "allowed_paths", None),
                    denied_paths=getattr(app.tool_policy, "denied_paths", None),
                )
                resolved_paths[param] = str(resolved)
            except Exception as exc:  # pragma: no cover - message surfaced in policy decision
                path_errors[param] = str(exc)

        decision: PolicyDecision
        if path_errors:
            reason = "; ".join(sorted(path_errors.values()))
            decision = PolicyDecision(False, f"Path validation failed: {reason}")
        else:
            decision = app.tool_policy.evaluate(tool, args, workspace=workspace)

        confirmation_needed = app.config.tools.confirmation_required and app._requires_confirmation(tool)

        meta_table = Table.grid(padding=(0, 1))
        meta_table.add_row("Tool:", tool.name)
        meta_table.add_row("Risk level:", getattr(tool, "risk_level", "unknown"))
        meta_table.add_row(
            "Capabilities:",
            f"emits_artifacts={getattr(tool, 'emits_artifacts', False)}, "
            f"requires_network={getattr(tool, 'requires_network', False)}, "
            f"requires_shell={getattr(tool, 'requires_shell', False)}",
        )
        meta_table.add_row("Path params:", ", ".join(getattr(tool, "path_params", ())) or "none")
        if resolved_paths:
            meta_table.add_row("Resolved paths:", "; ".join(f"{k} -> {v}" for k, v in resolved_paths.items()))
        if path_errors:
            meta_table.add_row("Path issues:", "; ".join(f"{k}: {v}" for k, v in path_errors.items()))

        status = "ALLOW" if decision.allowed else "DENY"
        meta_table.add_row("Policy result:", f"{status} ({decision.reason})")
        meta_table.add_row("Confirmation required:", "yes" if confirmation_needed else "no")

        console.print(Panel(meta_table, title="Policy explain", border_style="cyan"))
