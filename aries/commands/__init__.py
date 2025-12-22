"""
Command system for Aries.

Commands are slash-prefixed actions like /model, /rag, /help, etc.
"""

from aries.commands.base import BaseCommand
from aries.commands.model import ModelCommand
from aries.commands.clear import ClearCommand
from aries.commands.help import HelpCommand
from aries.commands.exit import ExitCommand
from aries.commands.rag import RAGCommand
from aries.commands.search import SearchCommand

# Command registry
COMMANDS: dict[str, type[BaseCommand]] = {
    "model": ModelCommand,
    "clear": ClearCommand,
    "help": HelpCommand,
    "exit": ExitCommand,
    "quit": ExitCommand,  # Alias
    "rag": RAGCommand,
    "search": SearchCommand,
}


def is_command(input_str: str) -> bool:
    """Check if input is a command.
    
    Args:
        input_str: User input string.
        
    Returns:
        True if input starts with '/'.
    """
    return input_str.strip().startswith("/")


def get_command(name: str) -> BaseCommand | None:
    """Get command instance by name.
    
    Args:
        name: Command name (without slash).
        
    Returns:
        Command instance or None if not found.
    """
    cmd_class = COMMANDS.get(name.lower())
    if cmd_class is None:
        return None
    return cmd_class()


def get_all_commands() -> dict[str, str]:
    """Get all commands with descriptions.
    
    Returns:
        Dictionary of command names to descriptions.
    """
    result = {}
    seen_classes = set()
    
    for name, cmd_class in COMMANDS.items():
        # Skip aliases (same class)
        if cmd_class in seen_classes:
            continue
        seen_classes.add(cmd_class)
        
        instance = cmd_class()
        result[name] = instance.description
    
    return result


__all__ = [
    "BaseCommand",
    "is_command", 
    "get_command",
    "get_all_commands",
    "COMMANDS",
]
