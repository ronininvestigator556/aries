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
        args = args.strip().lstrip("/")
        
        if not args:
            # Show all commands
            commands = get_all_commands()
            display_command_help(commands)

            if hasattr(app, "tool_registry"):
                from rich.console import Console

                console = Console()
                console.print("\n[bold]Available Tools:[/bold]\n")
                tool_ids = sorted(app.tool_registry.list_tool_ids(), key=lambda tid: tid.qualified)
                for tid in tool_ids:
                    suffix = f" (unqualified: {tid.tool_name})" if tid.is_qualified else ""
                    console.print(f"  [cyan]{tid.qualified}[/cyan]{suffix}")
                console.print()
        else:
            # Show help for specific command
            cmd = get_command(args)
            if cmd is None:
                display_error(f"Unknown command: {args}")
                return
            
            from rich.console import Console
            console = Console()
            console.print(f"\n{cmd.get_help()}\n")
