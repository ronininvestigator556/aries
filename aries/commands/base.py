"""
Base command class for Aries commands.
"""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aries.cli import Aries


class BaseCommand(ABC):
    """Abstract base class for commands."""
    
    name: str = ""
    description: str = ""
    usage: str = ""
    
    @abstractmethod
    async def execute(self, app: "Aries", args: str) -> None:
        """Execute the command.
        
        Args:
            app: The Aries application instance.
            args: Command arguments string.
        """
        pass
    
    def get_help(self) -> str:
        """Get detailed help for this command.
        
        Returns:
            Help text string.
        """
        help_text = f"/{self.name}"
        if self.usage:
            help_text += f" {self.usage}"
        help_text += f"\n\n{self.description}"
        return help_text
