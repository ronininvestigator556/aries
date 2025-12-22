"""Tool registry with provider provenance support."""

from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from aries.providers.base import Provider
from aries.tools.base import BaseTool


class ToolRegistry:
    """Registry that tracks providers and their tools."""

    def __init__(self) -> None:
        self._providers: dict[str, Provider] = {}
        self._tools: dict[str, BaseTool] = {}

    @property
    def providers(self) -> dict[str, Provider]:
        """Registered providers keyed by provider_id."""
        return dict(self._providers)

    @property
    def tools(self) -> dict[str, BaseTool]:
        """Registered tools keyed by tool name."""
        return dict(self._tools)

    def register_provider(self, provider: Provider) -> None:
        """Register a provider and its tools.

        Raises:
            ValueError: If a provider id is reused or a tool name collision occurs.
        """
        if provider.provider_id in self._providers:
            raise ValueError(f"Provider '{provider.provider_id}' already registered")

        new_tools = provider.list_tools()
        collisions = self._detect_collisions(provider.provider_id, (tool.name for tool in new_tools))
        if collisions:
            guidance = "; ".join(
                f"'{name}' from providers {sorted(ids)}" for name, ids in sorted(collisions.items())
            )
            raise ValueError(
                "Tool name collision detected. "
                f"Conflicts: {guidance}. Use qualified names like 'provider:tool' in the future."
            )

        self._providers[provider.provider_id] = provider
        for tool in new_tools:
            setattr(tool, "provider_id", provider.provider_id)
            setattr(tool, "provider_version", provider.provider_version)
            self._tools[tool.name] = tool

    def resolve(self, name: str) -> BaseTool | None:
        """Return a tool by name."""
        return self._tools.get(name)

    def list_tools(self) -> list[BaseTool]:
        """List all registered tools."""
        return list(self._tools.values())

    def tools_by_provider(self) -> dict[str, list[BaseTool]]:
        """Return tools grouped by provider id."""
        grouped: dict[str, list[BaseTool]] = defaultdict(list)
        for tool in self._tools.values():
            provider_id = getattr(tool, "provider_id", "")
            grouped[provider_id].append(tool)
        return grouped

    def _detect_collisions(self, provider_id: str, names: Iterable[str]) -> dict[str, set[str]]:
        """Detect tool name collisions across providers."""
        collisions: dict[str, set[str]] = {}
        for name in names:
            if name in self._tools:
                existing_provider = getattr(self._tools[name], "provider_id", "unknown")
                collisions.setdefault(name, set()).update({existing_provider, provider_id})
        return collisions
