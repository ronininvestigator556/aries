"""
/workspace command - manage workspaces and persistence.
"""

from pathlib import Path
from typing import TYPE_CHECKING

from aries.commands.base import BaseCommand
from aries.ui.display import display_error, display_info, display_success

if TYPE_CHECKING:
    from aries.cli import Aries


class WorkspaceCommand(BaseCommand):
    """Create, open, list, close, export, or import workspaces."""

    name = "workspace"
    description = "Manage persistent workspaces"
    usage = "list|new <name>|open <name>|close|export <path>|import <bundle>"

    async def execute(self, app: "Aries", args: str) -> None:
        args = args.strip()
        if not args or args == "list":
            names = app.workspace.list()
            if not names:
                display_info("No workspaces found.")
                return
            active = app.workspace.current.name if app.workspace.current else None
            display_info("Workspaces:")
            for name in names:
                marker = " (active)" if active == name else ""
                display_info(f"- {name}{marker}")
            return

        if args.startswith("new "):
            name = args.split(maxsplit=1)[1]
            ws = app.workspace.new(name)
            app._apply_workspace_index_path()
            display_success(f"Workspace '{ws.name}' created and opened.")
            return

        if args.startswith("open "):
            name = args.split(maxsplit=1)[1]
            try:
                ws = app.workspace.open(name)
            except FileNotFoundError as exc:
                display_error(str(exc))
                return
            app._apply_workspace_index_path()
            display_success(f"Workspace '{ws.name}' opened.")
            return

        if args == "close":
            app.workspace.close()
            display_success("Workspace closed.")
            return

        if args.startswith("export "):
            path = Path(args.split(maxsplit=1)[1]).expanduser()
            try:
                bundle = app.workspace.export(path)
            except Exception as exc:
                display_error(f"Export failed: {exc}")
                return
            display_success(f"Workspace exported to {bundle}")
            return

        if args.startswith("import "):
            bundle = Path(args.split(maxsplit=1)[1]).expanduser()
            try:
                ws = app.workspace.import_bundle(bundle)
            except Exception as exc:
                display_error(f"Import failed: {exc}")
                return
            app._apply_workspace_index_path()
            display_success(f"Workspace '{ws.name}' imported and opened.")
            return

        display_error(f"Unknown workspace command: {args}")
