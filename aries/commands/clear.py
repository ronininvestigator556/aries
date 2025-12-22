"""
/clear command - Clear conversation history.
"""

from typing import TYPE_CHECKING

from aries.commands.base import BaseCommand
from aries.ui.display import display_success

if TYPE_CHECKING:
    from aries.cli import Aries


class ClearCommand(BaseCommand):
    """Clear conversation history."""
    
    name = "clear"
    description = "Clear the conversation history"
    usage = ""
    
    async def execute(self, app: "Aries", args: str) -> None:
        """Execute clear command.
        
        Args:
            app: Aries application instance.
            args: Unused.
        """
        app.conversation.clear()
        display_success("Conversation cleared")
