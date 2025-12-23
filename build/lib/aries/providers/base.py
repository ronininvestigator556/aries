"""Provider interfaces for Aries tools."""

from __future__ import annotations

from typing import Protocol

from aries.tools.base import BaseTool


class Provider(Protocol):
    """Protocol describing a tool provider.

    Providers surface tools to Aries while supplying provenance metadata.
    """

    provider_id: str
    provider_version: str

    def list_tools(self) -> list[BaseTool]:
        """Return tools supplied by this provider."""

