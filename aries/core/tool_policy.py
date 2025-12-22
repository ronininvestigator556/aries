"""
Tool policy enforcement and audit logging.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aries.config import ToolsConfig
from aries.core.workspace import resolve_and_validate_path
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

    def _path_allowed(self, path: str | None, workspace: Path | None) -> bool:
        if not path:
            return True
        try:
            resolve_and_validate_path(
                path,
                workspace=workspace,
                allowed_paths=self.allowed_paths,
                denied_paths=self.denied_paths,
            )
            return True
        except Exception:
            return False

    def evaluate(self, tool: BaseTool, args: dict[str, Any], *, workspace: Path | None = None) -> PolicyDecision:
        risk = getattr(tool, "risk_level", "read")
        mutates_state = bool(getattr(tool, "mutates_state", False))

        if getattr(tool, "requires_shell", False) and not self.config.allow_shell:
            return PolicyDecision(False, f"Shell execution disabled by policy (risk={risk})")

        if getattr(tool, "requires_network", False) and not self.config.allow_network:
            return PolicyDecision(False, f"Network tools disabled by policy (risk={risk})")

        for path_param in getattr(tool, "path_params", ()):
            if not self._path_allowed(args.get(path_param), workspace):
                return PolicyDecision(False, f"Path access denied by policy (risk={risk})")

        classification = "mutating" if mutates_state else "read"
        return PolicyDecision(True, f"allowed:{risk}:{classification}")
