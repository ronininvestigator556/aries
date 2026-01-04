from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from aries.cli import Aries
from aries.config import Config
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
async def test_desktop_plan_produces_steps_without_execution(tmp_path) -> None:
    config = Config()
    config.desktop_ops.enabled = True
    config.desktop_ops.mode = "commander"
    config.workspace.root = tmp_path / "workspaces"

    app = Aries(config)
    app.workspace.new("demo")

    shell_tool = DummyShellTool()
    app.tool_registry.register_provider(DummyProvider([shell_tool]))

    controller = DesktopOpsController(app, mode="commander")
    output, _ = await controller.plan("run tests")

    assert "Steps:" in output
    assert "tool=" in output
    assert "approval_required=yes" in output
    shell_tool._execute_mock.assert_not_called()


@pytest.mark.asyncio
async def test_desktop_dry_run_skips_exec_tools(tmp_path) -> None:
    config = Config()
    config.desktop_ops.enabled = True
    config.desktop_ops.mode = "commander"
    config.workspace.root = tmp_path / "workspaces"

    app = Aries(config)
    app.workspace.new("demo")

    shell_tool = DummyShellTool()
    app.tool_registry.register_provider(DummyProvider([shell_tool]))

    controller = DesktopOpsController(app, mode="commander")
    _, audit_log = await controller.plan("run tests", dry_run=True)

    assert any(entry.get("event") == "probe_skipped" for entry in audit_log)
    shell_tool._execute_mock.assert_not_called()
