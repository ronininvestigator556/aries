from __future__ import annotations

import pytest

from aries.core.tool_registry import AmbiguousToolError, ToolRegistry
from aries.providers.base import Provider
from aries.providers.core import CoreProvider
from aries.tools import TOOLS
from aries.tools.base import BaseTool, ToolResult


class _CollidingTool(BaseTool):
    name = "read_file"
    description = "collision test"

    @property
    def parameters(self) -> dict[str, object]:
        return {}

    async def execute(self, **kwargs: object) -> ToolResult:  # pragma: no cover - unused
        return ToolResult(success=True, content="ok")


class _CollidingProvider(Provider):
    provider_id = "collision"
    provider_version = "0.0.1"

    def list_tools(self) -> list[BaseTool]:
        return [_CollidingTool()]


def test_core_provider_registration_and_resolution() -> None:
    registry = ToolRegistry()
    registry.register_provider(CoreProvider())

    assert len(registry.list_tools()) == len(TOOLS)
    resolved = registry.resolve("read_file")
    assert resolved is not None
    assert resolved.provider_id == "core"
    assert resolved.provider_version


def test_tool_name_collision_raises_actionable_error() -> None:
    registry = ToolRegistry()
    registry.register_provider(CoreProvider())

    registry.register_provider(_CollidingProvider())

    with pytest.raises(AmbiguousToolError) as exc:
        registry.resolve("read_file")

    message = str(exc.value)
    assert "ambiguous" in message
    assert "core:read_file" in message
    assert "collision:read_file" in message

    resolved = registry.resolve("core:read_file")
    assert resolved is not None
    assert getattr(resolved, "provider_id", "") == "core"

    resolved_collision = registry.resolve("collision:read_file")
    assert resolved_collision is not None
    assert getattr(resolved_collision, "provider_id", "") == "collision"


def test_resolve_with_id_supports_qualified_and_unqualified() -> None:
    registry = ToolRegistry()
    registry.register_provider(CoreProvider())

    qualified = registry.resolve_with_id("core:write_file")
    assert qualified is not None
    tool_id, tool = qualified
    assert tool_id.qualified == "core:write_file"
    assert tool.name == "write_file"

    unqualified = registry.resolve_with_id("write_file")
    assert unqualified is not None
    assert unqualified[0].tool_name == "write_file"
