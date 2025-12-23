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
        if not app.last_action_details:
            console.print("[yellow]No actions recorded yet.[/yellow]")
            return
        
        console.print("[bold]Last Action Details:[/bold]")
        # Use simple string dump if it's not JSON serializable, but it should be since we built it.
        try:
            console.print(JSON(json.dumps(app.last_action_details, default=str)))
        except Exception:
            console.print(app.last_action_details)
