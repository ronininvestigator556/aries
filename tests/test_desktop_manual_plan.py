from __future__ import annotations

import unittest.mock
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from aries.cli import Aries
from aries.config import Config, MCPServerConfig
from aries.core.desktop_ops import DesktopOpsController
from aries.providers.base import Provider
from aries.tools.base import BaseTool, ToolResult


class DummyShellTool(BaseTool):
    name = "shell"
    description = "Dummy shell tool."
    requires_shell = True
    risk_level = "exec"

    def __init__(self) -> None:
        self._execute_mock = AsyncMock(return_value=ToolResult(success=True, content="ok"))

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {"command": {"type": "string"}},
            "required": ["command"],
        }

    async def execute(self, command: str, **kwargs: object) -> ToolResult:
        return await self._execute_mock(command=command, **kwargs)


class DummyProvider(Provider):
    provider_id = "dummy"
    provider_version = "1.0"

    def __init__(self, tools: list[BaseTool]) -> None:
        self._tools = tools

    def list_tools(self) -> list[BaseTool]:
        return self._tools


@pytest.mark.asyncio
async def test_desktop_plan_manual_fallback(tmp_path: Path) -> None:
    config = Config()
    config.desktop_ops.enabled = True
    config.desktop_ops.mode = "commander"
    config.desktop_ops.server_id = "desktop_commander"
    config.workspace.root = tmp_path / "workspaces"
    
    # Add dummy MCP server config to satisfy initialization checks
    config.providers.mcp.enabled = True
    config.providers.mcp.servers = [
        MCPServerConfig(id="desktop_commander", command=["echo", "dummy"])
    ]

    shell_tool = DummyShellTool()
    
    # Mock DesktopCommanderProvider to avoid actually trying to run the command
    with unittest.mock.patch("aries.cli.DesktopCommanderProvider") as mock_provider_cls:
        mock_instance = mock_provider_cls.return_value
        mock_instance.provider_id = "mcp:desktop_commander"
        mock_instance.list_tools.return_value = [shell_tool]
        app = Aries(config)

    app.workspace.new("test")

    # Mock Ollama response for _propose_plan
    app.ollama = AsyncMock()
    app.ollama.chat.return_value = {
        "message": {
            "content": "1. Step one\n2. Step two"
        }
    }
    app.current_model = "test-model"

    controller = DesktopOpsController(app, mode="commander")
    
    # "list files" should NOT match any recipe in desktop_recipes.py
    output, _ = await controller.plan("list files in C:\\Users\\muram\\Documents")

    # Current behavior: returns "Steps: (none)"
    # Desired behavior: returns the manual plan from LLM
    assert "Steps: (none)" not in output
    assert "Step one" in output
    assert "Step two" in output
