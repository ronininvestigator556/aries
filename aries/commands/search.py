"""
/search command - Manual web search via SearXNG.
"""

from typing import TYPE_CHECKING

from aries.commands.base import BaseCommand
from aries.tools.web_search import WebSearchTool
from aries.ui.display import display_error, display_info

if TYPE_CHECKING:
    from aries.cli import Aries


class SearchCommand(BaseCommand):
    """Perform a web search."""

    name = "search"
    description = "Search the web using DuckDuckGo"
    usage = "<query>"

    async def execute(self, app: "Aries", args: str) -> None:
        query = args.strip()
        if not query:
            display_error("Usage: /search <query>")
            return

        tool = WebSearchTool()
        result = await tool.execute(query=query)
        if result.success:
            display_info(result.content or "No results.")
        else:
            display_error(result.error or "Search failed.")
