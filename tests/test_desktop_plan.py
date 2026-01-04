from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from aries.cli import Aries
from aries.config import Config
from aries.core.desktop_ops import DesktopOpsController
from aries.core.desktop_recipes import RecipeMatch, RecipePlan, RecipeStep
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


class DummyReadTool(BaseTool):
    name = "dummy_read"
    description = "Dummy read tool."
    risk_level = "read"

    def __init__(self) -> None:
        self._execute_mock = AsyncMock(return_value=ToolResult(success=True, content="ok"))

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {"path": {"type": "string"}, "mode": {"type": "string"}},
            "required": ["path", "mode"],
        }

    async def execute(self, path: str, mode: str, **kwargs: object) -> ToolResult:
        return await self._execute_mock(path=path, mode=mode, **kwargs)


class DummyWriteTool(BaseTool):
    name = "dummy_write"
    description = "Dummy write tool."
    mutates_state = True
    risk_level = "write"

    def __init__(self) -> None:
        self._execute_mock = AsyncMock(return_value=ToolResult(success=True, content="ok"))

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
            "required": ["path", "content"],
        }

    async def execute(self, path: str, content: str, **kwargs: object) -> ToolResult:
        return await self._execute_mock(path=path, content=content, **kwargs)


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
async def test_desktop_plan_deterministic_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = Config()
    config.desktop_ops.enabled = True
    config.desktop_ops.mode = "commander"
    config.workspace.root = tmp_path / "workspaces"

    app = Aries(config)
    app.workspace.new("demo")

    read_tool = DummyReadTool()
    write_tool = DummyWriteTool()
    app.tool_registry.register_provider(DummyProvider([read_tool, write_tool]))

    controller = DesktopOpsController(app, mode="commander")

    steps = [
        RecipeStep(
            name="write-step",
            tool_name="dummy_write",
            arguments={"content": "hi", "path": "notes.txt"},
        ),
        RecipeStep(
            name="read-step",
            tool_name="dummy_read",
            arguments={"mode": "r", "path": "notes.txt"},
        ),
    ]
    plan = RecipePlan(name="demo", steps=steps, done_criteria=lambda *_: True)
    match = RecipeMatch(name="demo", arguments={}, reason="test")

    monkeypatch.setattr(controller.recipe_registry, "match_goal", lambda *_: match)
    monkeypatch.setattr(controller.recipe_registry, "plan", lambda *_: plan)

    first_output, _ = await controller.plan("demo")
    second_output, _ = await controller.plan("demo")

    assert first_output == second_output
    lines = first_output.splitlines()
    read_index = next(index for index, line in enumerate(lines) if "dummy_read" in line)
    write_index = next(index for index, line in enumerate(lines) if "dummy_write" in line)
    assert read_index < write_index
    args_line = lines[read_index + 1]
    assert args_line.index('"mode": "r"') < args_line.index('"path": "notes.txt"')


@pytest.mark.asyncio
async def test_desktop_dry_run_skips_exec_tools(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = Config()
    config.desktop_ops.enabled = True
    config.desktop_ops.mode = "commander"
    config.workspace.root = tmp_path / "workspaces"

    app = Aries(config)
    app.workspace.new("demo")

    read_tool = DummyReadTool()
    write_tool = DummyWriteTool()
    app.tool_registry.register_provider(DummyProvider([read_tool, write_tool]))

    controller = DesktopOpsController(app, mode="commander")

    steps = [
        RecipeStep(
            name="read-step",
            tool_name="dummy_read",
            arguments={"mode": "r", "path": "notes.txt"},
        ),
        RecipeStep(
            name="write-step",
            tool_name="dummy_write",
            arguments={"path": "notes.txt", "content": "hello"},
        ),
    ]
    plan = RecipePlan(name="demo", steps=steps, done_criteria=lambda *_: True)
    match = RecipeMatch(name="demo", arguments={}, reason="test")

    monkeypatch.setattr(controller.recipe_registry, "match_goal", lambda *_: match)
    monkeypatch.setattr(controller.recipe_registry, "plan", lambda *_: plan)

    output, audit_log = await controller.plan("demo", dry_run=True)

    assert "probe=true" in output
    assert any(entry.get("event") == "probe_skipped" for entry in audit_log)
    read_tool._execute_mock.assert_called()
    write_tool._execute_mock.assert_not_called()
    assert any(
        entry.get("event") == "tool_call" and entry.get("probe") is True for entry in audit_log
    )
