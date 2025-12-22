"""
/exit command - Exit Aries.
"""

from typing import TYPE_CHECKING

from rich.console import Console

from aries.commands.base import BaseCommand

if TYPE_CHECKING:
    from aries.cli import Aries


console = Console()


class ExitCommand(BaseCommand):
    """Exit Aries."""
    
    name = "exit"
    description = "Exit Aries"
    usage = ""
    
    async def execute(self, app: "Aries", args: str) -> None:
        """Execute exit command.
        
        Args:
            app: Aries application instance.
            args: Unused.
        """
        console.print("[dim]Goodbye![/dim]")
        app.stop()
