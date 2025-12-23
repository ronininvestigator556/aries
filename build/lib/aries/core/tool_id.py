"""Canonical tool identity representation."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ToolId:
    """Unique identifier for a tool with provider provenance."""

    provider_id: str | None
    tool_name: str
    server_id: str | None = None

    @property
    def qualified(self) -> str:
        """Qualified string form."""
        if not self.provider_id:
            return self.tool_name

        if self.provider_id == "core":
            return f"{self.provider_id}:{self.tool_name}"

        if self.provider_id == "mcp":
            server = self.server_id or ""
            return f"{self.provider_id}:{server}:{self.tool_name}"

        if self.server_id:
            return f"{self.provider_id}:{self.server_id}:{self.tool_name}"
        return f"{self.provider_id}:{self.tool_name}"

    @property
    def is_qualified(self) -> bool:
        """Whether the tool id has provider provenance."""
        return bool(self.provider_id)

    @classmethod
    def parse(cls, raw: str) -> "ToolId":
        """Parse either qualified or unqualified tool identifiers."""
        parts = raw.split(":")
        if len(parts) >= 2:
            provider_id = parts[0]
            if provider_id == "core":
                return cls(provider_id="core", server_id=None, tool_name=":".join(parts[1:]))
            if provider_id == "mcp" and len(parts) >= 3:
                return cls(provider_id="mcp", server_id=parts[1], tool_name=":".join(parts[2:]))
            if len(parts) == 2:
                return cls(provider_id=provider_id, server_id=None, tool_name=parts[1])
            if len(parts) >= 3:
                return cls(provider_id=provider_id, server_id=parts[1], tool_name=":".join(parts[2:]))

        return cls(provider_id=None, server_id=None, tool_name=raw)

    @classmethod
    def from_parts(cls, *, provider_id: str | None, tool_name: str, server_id: str | None = None) -> "ToolId":
        """Create a ToolId from structured parts."""
        return cls(provider_id=provider_id, server_id=server_id, tool_name=tool_name)

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.qualified
