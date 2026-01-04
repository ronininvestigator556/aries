from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from pathlib import Path

from aries.cli import Aries
from aries.config import Config
from aries.core.desktop_ops import DesktopOpsController
from aries.providers.base import Provider
from aries.tools.base import BaseTool, ToolResult


class DummyReadTool(BaseTool):
    name = "dummy_read"
    description = "Read-only dummy tool."
    risk_level = "read"
    mutates_state = False
    emits_artifacts = False
    path_params = ("path",)

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        }

    async def execute(self, **kwargs) -> ToolResult:
        return ToolResult(success=True, content="ok")


class DummyProvider(Provider):
    provider_id = "dummy"
    provider_version = "1.0"

    def list_tools(self) -> list[BaseTool]:
        return [DummyReadTool()]


@pytest.mark.asyncio
async def test_desktop_ops_executes_tool_calls(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = Config()
    config.desktop_ops.enabled = True
    config.desktop_ops.mode = "commander"
    config.workspace.root = tmp_path / "workspaces"

    app = Aries(config)
    app.workspace.new("demo")
    app.tool_registry.register_provider(DummyProvider())

    tool_calls = [
        {
            "id": "call_1",
            "type": "function",
            "function": {"name": "dummy_read", "arguments": {"path": str(app.workspace.current.root)}},
        }
    ]

    app.ollama.chat = AsyncMock(
        side_effect=[
            {"message": {"tool_calls": tool_calls}},
            {"message": {"content": "DONE: completed"}}
        ]
    )

    monkeypatch.setattr("aries.core.desktop_ops.get_user_input", AsyncMock(return_value="y"))

    controller = DesktopOpsController(app, mode="commander")
    result = await controller.run("Read the workspace root.")

    assert result.status == "completed"
    assert "success" in result.summary.lower()


@pytest.mark.asyncio
async def test_desktop_ops_denies_path_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = Config()
    config.desktop_ops.enabled = True
    config.desktop_ops.mode = "commander"
    config.desktop_ops.max_retries_per_step = 0
    config.workspace.root = tmp_path / "workspaces"

    app = Aries(config)
    app.workspace.new("demo")
    app.tool_registry.register_provider(DummyProvider())

    outside_path = tmp_path / "outside.txt"
    tool_calls = [
        {
            "id": "call_2",
            "type": "function",
            "function": {"name": "dummy_read", "arguments": {"path": str(outside_path)}},
        }
    ]

    app.ollama.chat = AsyncMock(side_effect=[{"message": {"tool_calls": tool_calls}}])
    monkeypatch.setattr("aries.core.desktop_ops.get_user_input", AsyncMock(return_value="n"))

    controller = DesktopOpsController(app, mode="commander")
    result = await controller.run("Attempt to read outside workspace.")

    assert "blocked" in result.summary.lower()
