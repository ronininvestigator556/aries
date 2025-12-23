"""
Input handling for Aries CLI.
"""

import asyncio
from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.styles import Style
from pathlib import Path


# Define prompt style
PROMPT_STYLE = Style.from_dict({
    "prompt": "cyan bold",
    "": "",  # Default text
})


# Create history file in user's home directory
def _get_history_path() -> Path:
    """Get path to history file."""
    history_dir = Path.home() / ".aries"
    history_dir.mkdir(exist_ok=True)
    return history_dir / "history"


from prompt_toolkit.formatted_text import HTML
from typing import Callable, Any

# Global session (lazy initialized)
_session: PromptSession | None = None


def _get_session() -> PromptSession:
    """Get or create prompt session."""
    global _session
    if _session is None:
        _session = PromptSession(
            history=FileHistory(str(_get_history_path())),
            auto_suggest=AutoSuggestFromHistory(),
            style=PROMPT_STYLE,
            multiline=False,
            enable_history_search=True,
        )
    return _session


async def get_user_input(
    prompt: str = ">>> ",
    status_callback: Callable[[], Any] | None = None,
    default: str = "",
) -> str:
    """Get user input asynchronously.
    
    Args:
        prompt: Prompt string to display.
        status_callback: Optional callback that returns content for the bottom toolbar.
        default: Default text to pre-fill in the prompt.
        
    Returns:
        User's input string.
    """
    session = _get_session()
    
    # Run prompt_toolkit in thread pool since it's blocking
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None,
        lambda: session.prompt(
            [("class:prompt", prompt)],
            bottom_toolbar=status_callback,
            default=default,
        )
    )
    return result


async def get_multiline_input(prompt: str = ">>> ") -> str:
    """Get multiline user input.
    
    Use triple backticks to start/end multiline mode.
    
    Args:
        prompt: Prompt string to display.
        
    Returns:
        User's input string (potentially multiline).
    """
    first_line = await get_user_input(prompt)
    
    if not first_line.startswith("```"):
        return first_line
    
    # Multiline mode
    lines = [first_line[3:]]  # Remove opening ```
    
    while True:
        line = await get_user_input("... ")
        if line.endswith("```"):
            lines.append(line[:-3])  # Remove closing ```
            break
        lines.append(line)
    
    return "\n".join(lines)
