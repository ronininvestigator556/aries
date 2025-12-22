"""
Web search tool using SearXNG.
"""

from typing import Any

import aiohttp

from aries.config import get_config
from aries.tools.base import BaseTool, ToolResult


class WebSearchTool(BaseTool):
    """Perform a web search via SearXNG."""

    name = "search_web"
    description = "Search the web using the configured SearXNG instance"

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
        url = f"{config.searxng_url}/search"
        params = {"q": query, "format": "json", "limit": limit}

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, timeout=config.timeout) as resp:
                    if resp.status != 200:
                        return ToolResult(
                            success=False,
                            content="",
                            error=f"SearXNG returned status {resp.status}",
                        )
                    data = await resp.json()
        except Exception as exc:
            return ToolResult(success=False, content="", error=str(exc))

        results = data.get("results", [])[:limit]
        lines = [f"{item.get('title','')} - {item.get('url','')}" for item in results]
        content = "\n".join(lines) if lines else "No results."
        return ToolResult(success=True, content=content, metadata={"results": results})
