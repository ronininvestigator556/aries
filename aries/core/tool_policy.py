"""
Tool policy enforcement and audit logging.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aries.config import ToolsConfig
from aries.tools.base import BaseTool


@dataclass
class PolicyDecision:
    allowed: bool
    reason: str


class ToolPolicy:
    """Evaluate whether a tool execution is permitted."""

    def __init__(self, config: ToolsConfig) -> None:
        self.config = config
        self.allowed_paths = [Path(p).expanduser().resolve() for p in config.allowed_paths]
        self.denied_paths = [Path(p).expanduser().resolve() for p in config.denied_paths]

    def _path_allowed(self, path: str | None) -> bool:
        if not path:
            return True
        try:
            resolved = Path(path).expanduser().resolve()
        except Exception:
            return False
        if any(str(resolved).startswith(str(denied)) for denied in self.denied_paths):
            return False
        if not self.allowed_paths:
            return True
        return any(str(resolved).startswith(str(allowed)) for allowed in self.allowed_paths)

    def evaluate(self, tool: BaseTool, args: dict[str, Any]) -> PolicyDecision:
        name = tool.name
        # Shell commands require explicit allow
        if name == "execute_shell":
            if not self.config.allow_shell:
                return PolicyDecision(False, "Shell execution disabled by policy")
            cwd = args.get("cwd")
            if cwd and not self._path_allowed(cwd):
                return PolicyDecision(False, "Working directory not permitted")
        # Web search requires network allow
        if name == "search_web" and not self.config.allow_network:
            return PolicyDecision(False, "Network tools disabled by policy")
        # File tools path checks
        if name in {"read_file", "write_file", "list_directory"}:
            path = args.get("path")
            if not self._path_allowed(path):
                return PolicyDecision(False, "Path access denied by policy")
        return PolicyDecision(True, "allowed")

