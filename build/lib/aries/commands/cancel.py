"""
Command to reset console state.
"""

from typing import TYPE_CHECKING

from rich.console import Console

from aries.commands.base import BaseCommand

if TYPE_CHECKING:
    from aries.cli import Aries

console = Console()


class CancelCommand(BaseCommand):
    name = "cancel"
    description = "Reset console state and clear running flags"
    usage = ""

    async def execute(self, app: "Aries", args: str) -> None:
        """Execute the cancel command."""
        app.last_action_status = "Idle"
        # In a single-threaded REPL, we can't be processing a task and running this command 
        # at the same time, but we can clean up any stale state.
        if app.processing_task and not app.processing_task.done():
            app.processing_task.cancel()
            console.print("[yellow]Cancelled background task.[/yellow]")
        
        console.print("[green]Console state reset.[/green]")
