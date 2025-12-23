"""
/search command - Manual web search via SearXNG.
"""

from typing import TYPE_CHECKING

from aries.commands.base import BaseCommand
from aries.core.message import ToolCall
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

        tool = app.tool_map.get("search_web", WebSearchTool())
        call = ToolCall(id="manual-search", name="search_web", arguments={"query": query})
        await app._execute_tool_calls([call])
