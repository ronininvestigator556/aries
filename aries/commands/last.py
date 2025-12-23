"""
Command to show details of the last action.
"""

import json
from typing import TYPE_CHECKING

from rich.console import Console
from rich.json import JSON

from aries.commands.base import BaseCommand

if TYPE_CHECKING:
    from aries.cli import Aries

console = Console()


class LastCommand(BaseCommand):
    name = "last"
    description = "Show details of the last tool execution or command"
    usage = ""

    async def execute(self, app: "Aries", args: str) -> None:
        """Show last action details."""
        entries = []
        if getattr(app, "last_action_details", None):
            ts = app.last_action_details.get("timestamp") if isinstance(app.last_action_details, dict) else None
            entries.append(("Last Action", app.last_action_details, ts))
        if getattr(app, "last_model_turn", None):
            ts = app.last_model_turn.get("timestamp") if isinstance(app.last_model_turn, dict) else None
            entries.append(("Last Model Turn", app.last_model_turn, ts))

        if not entries:
            console.print("[yellow]No actions recorded yet.[/yellow]")
            return
        
        entries.sort(key=lambda item: item[2] or 0, reverse=True)
        for label, payload, _ in entries:
            console.print(f"[bold]{label} Details:[/bold]")
            try:
                console.print(JSON(json.dumps(payload, default=str)))
            except Exception:
                console.print(payload)
