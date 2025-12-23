"""Tool registry with provider provenance support."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from aries.providers.base import Provider
from aries.tools.base import BaseTool
from aries.core.tool_id import ToolId


@dataclass(frozen=True)
class AmbiguousToolError(Exception):
    """Raised when an unqualified tool resolution is ambiguous."""

    name: str
    candidates: list[ToolId]

    def __str__(self) -> str:  # pragma: no cover - simple formatting
        qualified = ", ".join(sorted(c.qualified for c in self.candidates))
        return f"Tool name '{self.name}' is ambiguous. Use a qualified name: {qualified}"


class ToolRegistry:
    """Registry that tracks providers and their tools."""

    def __init__(self) -> None:
        self._providers: dict[str, Provider] = {}
        self._tools: dict[ToolId, BaseTool] = {}
        self._tools_by_name: dict[str, list[ToolId]] = defaultdict(list)

    @property
    def providers(self) -> dict[str, Provider]:
        """Registered providers keyed by provider_id."""
        return dict(self._providers)

    @property
    def tools(self) -> dict[str, BaseTool]:
        """Registered tools keyed by qualified tool id."""
        return {tool_id.qualified: tool for tool_id, tool in self._tools.items()}

    def register_provider(self, provider: Provider) -> None:
        """Register a provider and its tools.

        Raises:
            ValueError: If a provider id is reused.
        """
        if provider.provider_id in self._providers:
            raise ValueError(f"Provider '{provider.provider_id}' already registered")

        new_tools = provider.list_tools()
        self._providers[provider.provider_id] = provider
        for tool in new_tools:
            tool_id = self._make_tool_id(provider, tool)
            setattr(tool, "provider_id", tool_id.provider_id or "")
            setattr(tool, "provider_version", provider.provider_version)
            setattr(tool, "server_id", tool_id.server_id or "")
            setattr(tool, "tool_id", tool_id)
            setattr(tool, "qualified_id", tool_id.qualified)
            self._tools[tool_id] = tool
            self._tools_by_name[tool_id.tool_name].append(tool_id)

    def resolve(self, name: str) -> BaseTool | None:
        """Return a tool by name or None if missing.

        Raises:
            AmbiguousToolError: If an unqualified name matches multiple tools.
        """
        resolved = self.resolve_with_id(name)
        return resolved[1] if resolved else None

    def resolve_with_id(self, name: str) -> tuple[ToolId, BaseTool] | None:
        """Resolve a tool and return both its id and object."""
        candidate = ToolId.parse(name)
        if candidate.is_qualified:
            tool = self._tools.get(candidate)
            return (candidate, tool) if tool else None

        matches = self._tools_by_name.get(candidate.tool_name, [])
        if not matches:
            return None
        if len(matches) > 1:
            raise AmbiguousToolError(candidate.tool_name, matches)

        tool_id = matches[0]
        return tool_id, self._tools[tool_id]

    def list_tools(self) -> list[BaseTool]:
        """List all registered tools."""
        return list(self._tools.values())

    def list_tool_ids(self) -> list[ToolId]:
        """List all registered tool ids."""
        return list(self._tools.keys())

    def list_tool_definitions(self, *, qualified: bool = False) -> list[dict]:
        """Return tool definitions formatted for model consumption."""
        definitions = []
        for tool_id, tool in self._tools.items():
            name = tool_id.qualified if qualified else tool.name
            definitions.append(tool.to_ollama_format(name=name))
        return definitions

    def lookup_map(self, *, include_unqualified_unique: bool = True) -> dict[str, BaseTool]:
        """Build a lookup map for tool name resolution."""
        mapping: dict[str, BaseTool] = {
            tool_id.qualified: tool for tool_id, tool in self._tools.items()
        }
        if include_unqualified_unique:
            for name, ids in self._tools_by_name.items():
                if len(ids) == 1:
                    mapping.setdefault(name, self._tools[ids[0]])
        return mapping

    def tools_by_server(self) -> dict[str, list[BaseTool]]:
        """Return tools grouped by server id when present."""
        grouped: dict[str, list[BaseTool]] = defaultdict(list)
        for tool in self._tools.values():
            server_id = getattr(tool, "server_id", "")
            if server_id:
                grouped[server_id].append(tool)
        return grouped

    def collisions(self) -> dict[str, list[ToolId]]:
        """Return unqualified names that have more than one provider."""
        return {name: ids for name, ids in self._tools_by_name.items() if len(ids) > 1}

    def tools_by_provider(self) -> dict[str, list[BaseTool]]:
        """Return tools grouped by provider id."""
        grouped: dict[str, list[BaseTool]] = defaultdict(list)
        for tool_id, tool in self._tools.items():
            provider_id = getattr(tool, "provider_key", None) or getattr(tool, "provider_id", "")
            grouped[provider_id].append(tool)
        return grouped

    def items(self) -> list[tuple[ToolId, BaseTool]]:
        """Return tool id/tool pairs for inspection."""
        return list(self._tools.items())

    def _make_tool_id(self, provider: Provider, tool: BaseTool) -> ToolId:
        """Build a ToolId from provider and tool metadata."""
        provider_id = provider.provider_id.split(":", 1)[0]
        server_id = getattr(provider, "server_id", None) or getattr(tool, "server_id", None)

        # Preserve the full provider identifier for provenance reporting.
        setattr(tool, "provider_key", provider.provider_id)

        return ToolId.from_parts(provider_id=provider_id, server_id=server_id, tool_name=tool.name)
