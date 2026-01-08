from __future__ import annotations

from pathlib import Path
import sys
from unittest.mock import AsyncMock

import pytest

from aries.cli import Aries
from aries.config import Config
from aries.core.desktop_ops import DesktopOpsController, DesktopOpsMode, DesktopRisk
from aries.core.file_edit import FileEditPipeline
from aries.core.message import ToolCall
from aries.providers.base import Provider
from aries.tools.base import BaseTool, ToolResult


class DummyShellTool(BaseTool):
    name = "shell"
    description = "shell tool"
    requires_shell = True

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {"command": {"type": "string"}},
            "required": ["command"],
        }

    async def execute(self, command: str, **kwargs: object) -> ToolResult:
        return ToolResult(success=True, content=f"ran {command}")


class DummyPathTool(BaseTool):
    name = "path_tool"
    description = "path tool"
    risk_level = "read"
    path_params = ("path",)

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        }

    async def execute(self, path: str, **kwargs: object) -> ToolResult:
        return ToolResult(success=True, content=str(path))


class DummyProvider(Provider):
    provider_id = "dummy"
    provider_version = "1.0"

    def __init__(self, tools: list[BaseTool]) -> None:
        self._tools = tools

    def list_tools(self) -> list[BaseTool]:
        return self._tools


def _make_app(tmp_path: Path, tools: list[BaseTool]) -> Aries:
    config = Config()
    config.desktop_ops.enabled = True
    config.desktop_ops.mode = "commander"
    config.tools.allow_shell = True
    config.tools.confirmation_required = False
    config.workspace.root = tmp_path / "workspaces"

    app = Aries(config)
    app.workspace.new("demo")
    app.tool_registry.register_provider(DummyProvider(tools))
    return app


@pytest.mark.asyncio
async def test_recipe_steps_use_policy_gateway(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    app = _make_app(tmp_path, [DummyShellTool()])
    controller = DesktopOpsController(app, mode="commander")
    context = controller._build_context("run tests")

    monkeypatch.setattr("aries.core.desktop_ops.get_user_input", AsyncMock(return_value="y"))

    recipe_call = ToolCall(
        id="recipe",
        name="desktop.recipe.run_tests",
        arguments={"repo_root": str(app.workspace.current.root)},
    )
    await controller._execute_recipe(context, recipe_call)

    policy_entries = [entry for entry in context.audit_log if entry.get("event") == "policy_check"]
    assert policy_entries
    assert all(entry.get("recipe") == "run_tests" for entry in policy_entries)

    tool_call = ToolCall(id="call", name="shell", arguments={"command": "echo ok"})
    await controller._execute_call(context, tool_call)
    assert any(entry.get("recipe") is None for entry in context.audit_log if entry.get("event") == "policy_check")


def test_commander_mode_allows_read_only_and_allowlisted_exec(tmp_path: Path) -> None:
    app = _make_app(tmp_path, [DummyShellTool()])
    controller = DesktopOpsController(app, mode="commander")

    read_tool = DummyPathTool()
    assert controller._requires_approval(DesktopRisk.READ_ONLY, read_tool, {"path": "demo"}) is False

    args = {"command": "echo ok"}
    controller.config.auto_exec_allowlist = ["shell:echo ok"]
    assert controller._requires_approval(DesktopRisk.EXEC_USERSPACE, DummyShellTool(), args) is False

    controller.config.auto_exec_allowlist = []
    assert controller._requires_approval(DesktopRisk.EXEC_USERSPACE, DummyShellTool(), args) is True


def test_high_risk_requires_approval_unless_allowlisted(tmp_path: Path) -> None:
    app = _make_app(tmp_path, [DummyShellTool()])
    controller = DesktopOpsController(app, mode="commander")
    args = {"command": "curl"}

    controller.config.auto_exec_allowlist = []
    assert controller._requires_approval(DesktopRisk.NETWORK, DummyShellTool(), args) is True
    assert controller._requires_approval(DesktopRisk.EXEC_PRIVILEGED, DummyShellTool(), args) is True
    assert controller._requires_approval(DesktopRisk.WRITE_DESTRUCTIVE, DummyShellTool(), args) is True

    controller.config.auto_exec_allowlist = ["shell:curl"]
    assert controller._requires_approval(DesktopRisk.NETWORK, DummyShellTool(), args) is False


@pytest.mark.asyncio
async def test_path_validation_applies_to_tools_and_file_edit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = _make_app(tmp_path, [DummyPathTool()])
    controller = DesktopOpsController(app, mode="commander")
    context = controller._build_context("read file")

    monkeypatch.setattr("aries.core.desktop_ops.get_user_input", AsyncMock(return_value="n"))

    outside = tmp_path / "outside.txt"
    tool_call = ToolCall(id="call", name="path_tool", arguments={"path": str(outside)})
    await controller._execute_call(context, tool_call)

    policy_entries = [entry for entry in context.audit_log if entry.get("event") == "policy_check"]
    assert policy_entries
    assert any(not entry["paths_validated"]["path"]["allowed"] for entry in policy_entries)

    rel_call = ToolCall(id="rel", name="path_tool", arguments={"path": "../escape.txt"})
    await controller._execute_call(context, rel_call)
    rel_entries = [entry for entry in context.audit_log if entry.get("event") == "policy_check"]
    assert any(
        entry.get("paths_validated", {}).get("path", {}).get("allowed") is False
        for entry in rel_entries
        if entry.get("tool_id", "").endswith("path_tool")
    )

    pipeline = FileEditPipeline(workspace=app.workspace.current.root, allowed_paths=[app.workspace.current.root])
    diff = """--- a/escape.txt\n+++ b/escape.txt\n@@ -1 +1 @@\n-hello\n+goodbye\n"""
    result = pipeline.apply_patch("../escape.txt", diff)
    assert result.success is False

    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    (outside_dir / "target.txt").write_text("data", encoding="utf-8")
    link_path = app.workspace.current.root / "link.txt"
    link_path.symlink_to(outside_dir / "target.txt")
    symlink_result = pipeline.apply_patch(str(link_path), diff)
    assert symlink_result.success is False


@pytest.mark.asyncio
async def test_builtin_fs_tool_routes_through_policy(tmp_path: Path) -> None:
    app = _make_app(tmp_path, [])
    controller = DesktopOpsController(app, mode="commander")
    context = controller._build_context("read file")

    target = app.workspace.current.root / "note.txt"
    target.write_text("hello", encoding="utf-8")

    tool_call = ToolCall(
        id="call",
        name="builtin:fs:read_text",
        arguments={"path": str(target)},
    )
    await controller._execute_call(context, tool_call)

    policy_entries = [entry for entry in context.audit_log if entry.get("event") == "policy_check"]
    assert policy_entries
    assert any(entry.get("tool_id") == "builtin:fs:read_text" for entry in policy_entries)


@pytest.mark.asyncio
async def test_builtin_shell_tool_routes_through_policy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    app = _make_app(tmp_path, [])
    controller = DesktopOpsController(app, mode="commander")
    context = controller._build_context("run command")

    monkeypatch.setattr("aries.core.desktop_ops.get_user_input", AsyncMock(return_value="y"))

    tool_call = ToolCall(
        id="call",
        name="builtin:shell:run",
        arguments={
            "argv": [sys.executable, "-c", "print('ok')"],
            "cwd": str(app.workspace.current.root),
        },
    )
    await controller._execute_call(context, tool_call)

    policy_entries = [entry for entry in context.audit_log if entry.get("event") == "policy_check"]
    assert policy_entries
    assert any(entry.get("tool_id") == "builtin:shell:run" for entry in policy_entries)
