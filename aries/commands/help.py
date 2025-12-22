"""
/help command - Display help information.
"""

from typing import TYPE_CHECKING

from aries.commands.base import BaseCommand
from aries.commands import get_all_commands, get_command
from aries.ui.display import display_command_help, display_error

if TYPE_CHECKING:
    from aries.cli import Aries


class HelpCommand(BaseCommand):
    """Display help for commands."""
    
    name = "help"
    description = "Show available commands or help for a specific command"
    usage = "[command]"
    
    async def execute(self, app: "Aries", args: str) -> None:
        """Execute help command.
        
        Args:
            app: Aries application instance.
            args: Optional command name to get help for.
        """
        args = args.strip()
        
        if not args:
            # Show all commands
            commands = get_all_commands()
            display_command_help(commands)
        else:
            # Show help for specific command
            cmd = get_command(args)
            if cmd is None:
                display_error(f"Unknown command: {args}")
                return
            
            from rich.console import Console
            console = Console()
            console.print(f"\n{cmd.get_help()}\n")
