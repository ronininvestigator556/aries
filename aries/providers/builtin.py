"""Builtin provider exposing first-party filesystem tools."""

from __future__ import annotations

from aries import __version__
from aries.providers.base import Provider
from aries.tools.base import BaseTool
from aries.tools.builtin_filesystem import (
    BuiltinApplyPatchTool,
    BuiltinListDirTool,
    BuiltinReadTextTool,
    BuiltinSearchTextTool,
    BuiltinWriteTextTool,
)


class BuiltinProvider(Provider):
    """Provide builtin filesystem tools."""

    provider_id = "builtin"
    provider_version = __version__
    server_id = "fs"

    def list_tools(self) -> list[BaseTool]:
        return [
            BuiltinListDirTool(),
            BuiltinReadTextTool(),
            BuiltinWriteTextTool(),
            BuiltinSearchTextTool(),
            BuiltinApplyPatchTool(),
        ]
