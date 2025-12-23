"""Core provider exposing built-in Aries tools."""

from __future__ import annotations

from aries import __version__
from aries.providers.base import Provider
from aries.tools import get_all_tools
from aries.tools.base import BaseTool


class CoreProvider(Provider):
    """Provide built-in tools that ship with Aries."""

    provider_id = "core"
    provider_version = __version__

    def list_tools(self) -> list[BaseTool]:
        return get_all_tools()

