"""
Web search tool using DuckDuckGo.
"""

import asyncio
from typing import Any

from ddgs import DDGS

from aries.config import get_config
from aries.tools.base import BaseTool, ToolResult


class WebSearchTool(BaseTool):
    """Perform a web search via DuckDuckGo."""

    name = "search_web"
    description = "Search the web using DuckDuckGo"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query",
                },
                "num_results": {
                    "type": "integer",
                    "description": "Number of results to fetch",
                    "default": get_config().search.default_results,
                },
            },
            "required": ["query"],
        }

    async def execute(self, query: str, num_results: int | None = None, **_: Any) -> ToolResult:
        config = get_config().search
        limit = num_results or config.default_results

        try:
            # Use asyncio.to_thread because DDGS is a synchronous library
            with DDGS() as ddgs:
                results = await asyncio.to_thread(
                    lambda: list(ddgs.text(query, max_results=limit))
                )
        except Exception as exc:
            return ToolResult(success=False, content="", error=f"DuckDuckGo search failed: {exc}")

        if not results:
            return ToolResult(success=True, content="No results found.", metadata={"results": []})

        lines = []
        for item in results:
            title = item.get("title", "No Title")
            href = item.get("href", "No URL")
            body = item.get("body", "")
            lines.append(f"### {title}\nURL: {href}\n{body}\n")

        content = "\n".join(lines)
        return ToolResult(success=True, content=content, metadata={"results": results})
