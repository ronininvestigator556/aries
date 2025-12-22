from __future__ import annotations

import pytest

from aries.core.tool_registry import ToolRegistry
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

    with pytest.raises(ValueError) as exc:
        registry.register_provider(_CollidingProvider())

    message = str(exc.value)
    assert "Tool name collision detected" in message
    assert "qualified names" in message
    assert "core" in message
    assert "collision" in message

