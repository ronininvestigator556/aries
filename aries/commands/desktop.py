"""
/desktop command - Desktop Ops execution.
"""

from __future__ import annotations

import shlex
from typing import TYPE_CHECKING

from aries.commands.base import BaseCommand
from aries.core.desktop_ops import DesktopOpsController, DesktopOpsMode
from aries.ui.display import display_error, display_info, display_success, display_warning

if TYPE_CHECKING:
    from aries.cli import Aries


class DesktopCommand(BaseCommand):
    """Run Desktop Ops workflows."""

    name = "desktop"
    description = "Run Desktop Ops workflows"
    usage = (
        "<goal> | --summary-format <text|markdown|json> <goal> | "
        "--plan \"<goal>\" | --dry-run \"<goal>\" | mode <guide|commander|strict> | status"
    )

    async def execute(self, app: "Aries", args: str) -> None:
        args = args.strip()
        if not getattr(app.config, "desktop_ops", None) or not app.config.desktop_ops.enabled:
            display_error("Desktop Ops is disabled. Enable desktop_ops in config.yaml.")
            return

        if not args or args == "status":
            display_info(f"Desktop Ops mode: {app.desktop_ops_mode}")
            return

        if args.startswith("mode "):
            mode = args.split(maxsplit=1)[1].strip().lower()
            if mode not in {m.value for m in DesktopOpsMode}:
                display_error("Invalid mode. Use guide, commander, or strict.")
                return
            app.desktop_ops_mode = mode
            display_success(f"Desktop Ops mode set to {mode}.")
            return

        if not self._has_desktop_tools(app):
            display_error(
                "Desktop Ops requires a configured provider (desktop_commander or filesystem). "
                "Configure in config.yaml."
            )
            return

        tokens = shlex.split(args)
        summary_format = None
        if "--summary-format" in tokens:
            index = tokens.index("--summary-format")
            if index + 1 >= len(tokens):
                display_error("Provide a format after --summary-format (text, markdown, json).")
                return
            summary_format = tokens[index + 1].lower()
            if summary_format not in {"text", "markdown", "json"}:
                display_error("Invalid summary format. Use text, markdown, or json.")
                return
            del tokens[index : index + 2]
        if tokens and tokens[0] in {"--plan", "--dry-run"}:
            if len(tokens) < 2:
                display_error("Provide a request string after --plan or --dry-run.")
                return
            if not app.workspace.current:
                display_error("No workspace open. Use /workspace open <name> first.")
                return
            request = " ".join(tokens[1:])
            controller = DesktopOpsController(app, mode=app.desktop_ops_mode)
            plan_output, _ = await controller.plan(request, dry_run=tokens[0] == "--dry-run")
            display_info(plan_output)
            app.last_action_summary = plan_output
            app.last_action_status = "Planned" if tokens[0] == "--plan" else "Dry-run"
            return

        if not app.workspace.current:
            display_error("No workspace open. Use /workspace open <name> first.")
            return

        controller = DesktopOpsController(
            app,
            mode=app.desktop_ops_mode,
            summary_format=summary_format,
        )
        result = await controller.run(args)
        app.last_action_summary = result.summary
        app.last_action_status = result.status
        if result.run_log_path:
            display_info(f"Desktop Ops audit log: {result.run_log_path}")
        display_info(f"Desktop Ops summary:\\n{result.summary}")
        if result.status == "completed":
            display_success("Desktop Ops completed.")
        else:
            display_warning(f"Desktop Ops ended with status: {result.status}.")

    @staticmethod
    def _has_desktop_tools(app: "Aries") -> bool:
        providers = app.tool_registry.providers
        if "mcp:desktop" in providers:
            return True
        for tool in app.tool_registry.list_tools():
            if getattr(tool, "uses_filesystem_paths", False):
                return True
        return False
