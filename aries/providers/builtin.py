"""Builtin provider exposing first-party filesystem and shell tools."""

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
from aries.tools.builtin_shell import (
    BuiltinShellKillTool,
    BuiltinShellPollTool,
    BuiltinShellRunTool,
    BuiltinShellStartTool,
)
from aries.tools.builtin_web import (
    BuiltinWebExtractTool,
    BuiltinWebFetchTool,
    BuiltinWebSearchTool,
)


class BuiltinProvider(Provider):
    """Provide builtin filesystem and shell tools."""

    provider_id = "builtin"
    provider_version = __version__
    server_id = "fs"
    def list_tools(self) -> list[BaseTool]:
        return [
            BuiltinShellStartTool(),
            BuiltinShellPollTool(),
            BuiltinShellKillTool(),
            BuiltinShellRunTool(),
            BuiltinListDirTool(),
            BuiltinReadTextTool(),
            BuiltinWriteTextTool(),
            BuiltinSearchTextTool(),
            BuiltinApplyPatchTool(),
            BuiltinWebSearchTool(),
            BuiltinWebFetchTool(),
            BuiltinWebExtractTool(),
        ]
