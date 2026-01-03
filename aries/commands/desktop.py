"""
/desktop command - Desktop Ops execution.
"""

from __future__ import annotations

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
    usage = "<goal> | mode <guide|commander|strict> | status"

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

        if not app.workspace.current:
            display_error("No workspace open. Use /workspace open <name> first.")
            return

        controller = DesktopOpsController(app, mode=app.desktop_ops_mode)
        result = await controller.run(args)
        app.last_action_summary = result.summary
        app.last_action_status = result.status
        if result.run_log_path:
            display_info(f"Desktop Ops audit log: {result.run_log_path}")
        if result.status == "completed":
            display_success(result.summary)
        else:
            display_warning(result.summary)
