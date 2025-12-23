"""
/policy command - inspect tool policy status and dry-run decisions.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from rich.panel import Panel
from rich.table import Table
from rich.markup import escape

from aries.commands.base import BaseCommand
from aries.core.tool_policy import PolicyDecision
from aries.core.tool_registry import AmbiguousToolError
from aries.core.workspace import resolve_and_validate_path
from aries.ui.display import console, display_error

if TYPE_CHECKING:
    from aries.cli import Aries

from aries.providers.mcp import get_status, snapshot_statuses


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
        providers = app.tool_registry.providers if hasattr(app, "tool_registry") else {}
        tools_by_provider = app.tool_registry.tools_by_provider() if hasattr(app, "tool_registry") else {}
        tools_by_server = app.tool_registry.tools_by_server() if hasattr(app, "tool_registry") else {}
        collisions = app.tool_registry.collisions() if hasattr(app, "tool_registry") else {}
        provider_lines = [
            f"{pid} (v{getattr(provider, 'provider_version', 'unknown')}): {len(tools_by_provider.get(pid, []))} tools"
            for pid, provider in sorted(providers.items())
        ]
        server_lines = [
            f"{sid}: {len(tools_by_server.get(sid, []))} tools" for sid in sorted(tools_by_server)
        ]
        mcp_statuses = sorted(snapshot_statuses(), key=lambda entry: entry.server_id)
        mcp_lines: list[str] = []
        for entry in mcp_statuses:
            descriptor = (
                f"{entry.server_id} [{entry.transport}] "
                f"{entry.state}, tools={entry.tool_count}, "
                f"last_connect={entry.last_connect_at or 'n/a'}"
            )
            if entry.last_error:
                descriptor += f", last_error={entry.last_error}"
            mcp_lines.append(escape(descriptor))

        table = Table.grid(padding=(0, 1))
        table.add_row("Workspace:", workspace_label)
        table.add_row("Workspace root:", str(workspace.root) if workspace else "none")
        table.add_row("Tokens:", tokens_text)
        table.add_row("Tool enablement:", f"allow_shell={app.config.tools.allow_shell}, allow_network={app.config.tools.allow_network}")
        table.add_row("Confirmation:", "; ".join(confirmation_lines))
        if provider_lines:
            table.add_row("Providers:", "; ".join(provider_lines))
        if server_lines:
            table.add_row("Servers:", "; ".join(server_lines))
        if mcp_lines:
            table.add_row("MCP servers:", "; ".join(mcp_lines))
        if collisions:
            table.add_row("Tool collisions:", f"{len(collisions)} ambiguous name(s)")
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
        try:
            resolved = app.tool_registry.resolve_with_id(tool_name)
        except AmbiguousToolError as exc:
            candidates = ", ".join(sorted(c.qualified for c in exc.candidates))
            display_error(f"Tool '{tool_name}' is ambiguous. Candidates: {candidates}")
            return

        if not resolved:
            known = ", ".join(sorted(app.tool_registry.tools))
            display_error(f"Unknown tool: {tool_name}. Known tools: {known}")
            return

        tool_id, tool = resolved

        try:
            filtered_args = app._validate_tool_arguments(tool, args)
        except ValueError as exc:
            display_error(str(exc))
            return

        workspace = app.workspace.current.root if app.workspace.current else None
        resolved_paths: dict[str, str] = {}
        path_errors: dict[str, str] = {}

        for param in getattr(tool, "path_params", ()):
            if param not in filtered_args:
                continue
            try:
                resolved = resolve_and_validate_path(
                    filtered_args[param],
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
            decision = app.tool_policy.evaluate(tool, filtered_args, workspace=workspace)

        confirmation_needed = app.config.tools.confirmation_required and app._requires_confirmation(tool)

        meta_table = Table.grid(padding=(0, 1))
        meta_table.add_row("Tool:", tool_id.qualified)
        meta_table.add_row("Provider:", getattr(tool, "provider_id", "unknown"))
        meta_table.add_row("Provider version:", getattr(tool, "provider_version", "unknown"))
        server_id = getattr(tool, "server_id", None)
        if server_id:
            meta_table.add_row("Server:", server_id)
            status = get_status(server_id)
            if status:
                status_label = f"{status.state}"
                if status.state != "connected" and status.last_error:
                    status_label += f" (last_error={status.last_error})"
                meta_table.add_row("Server status:", status_label)
        meta_table.add_row("Risk level:", getattr(tool, "risk_level", "unknown"))
        meta_table.add_row(
            "Network requirements:",
            "transport="
            f"{getattr(tool, 'transport_requires_network', False)}, "
            "tool="
            f"{getattr(tool, 'tool_requires_network', False)}, "
            f"effective={getattr(tool, 'requires_network', False)}",
        )
        meta_table.add_row(
            "Capabilities:",
            f"emits_artifacts={getattr(tool, 'emits_artifacts', False)}, "
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
