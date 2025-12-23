"""
Palette UI component using prompt_toolkit.
"""

import asyncio
from typing import Dict, Optional

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import FuzzyCompleter, WordCompleter
from prompt_toolkit.shortcuts import CompleteStyle
from prompt_toolkit.styles import Style


PALETTE_STYLE = Style.from_dict({
    "prompt": "bold magenta",
})


async def show_palette_prompt(items: Dict[str, str]) -> Optional[str]:
    """Show an interactive fuzzy-search palette.
    
    Args:
        items: Dictionary mapping display strings (to be searched) to return values.
               e.g. {"/model - Manage models": "/model"}
               
    Returns:
        The selected return value (e.g. "/model") or None if cancelled.
    """
    candidates = list(items.keys())
    completer = FuzzyCompleter(WordCompleter(candidates, sentence=True))
    
    session = PromptSession(style=PALETTE_STYLE)
    
    loop = asyncio.get_event_loop()
    try:
        selection = await loop.run_in_executor(
            None,
            lambda: session.prompt(
                "Palette > ",
                completer=completer,
                complete_style=CompleteStyle.MULTI_COLUMN,
            )
        )
        return items.get(selection)
    except (KeyboardInterrupt, EOFError):
        return None
