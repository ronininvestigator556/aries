from __future__ import annotations

from unittest.mock import AsyncMock
import json

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


@pytest.mark.asyncio
async def test_desktop_ops_audit_log_paths_resolve(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    config = Config()
    config.desktop_ops.enabled = True
    config.desktop_ops.mode = "commander"
    config.workspace.root = Path("workspaces")
    config.prompts.directory = (Path(__file__).resolve().parents[1] / "prompts")

    app = Aries(config)
    app.workspace.new("demo")

    app.ollama.chat = AsyncMock(return_value={"message": {"content": "DONE: ok"}})

    controller = DesktopOpsController(app, mode="commander")
    result = await controller.run("No-op.")

    assert result.run_log_path is not None
    expected_dir = (tmp_path / "workspaces" / "demo" / "artifacts").resolve()
    assert result.run_log_path.parent.resolve() == expected_dir

    manifest_path = expected_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    audit_record = next(
        entry for entry in manifest if entry["path"] == str(result.run_log_path.resolve())
    )
    assert audit_record["path"].startswith(str(expected_dir))


@pytest.mark.asyncio
async def test_desktop_ops_empty_model_output_uses_recipe_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = Config()
    config.desktop_ops.enabled = True
    config.desktop_ops.mode = "commander"
    config.workspace.root = tmp_path / "workspaces"
    config.tools.confirmation_required = False

    app = Aries(config)
    app.workspace.new("demo")

    app.ollama.chat = AsyncMock(return_value={"message": {"content": ""}})

    controller = DesktopOpsController(app, mode="commander")
    match_calls = {"count": 0}
    original_match = controller.recipe_registry.match_goal

    def _match_goal(goal: str, context):
        match_calls["count"] += 1
        if match_calls["count"] == 1:
            return None
        return original_match(goal, context)

    monkeypatch.setattr(controller.recipe_registry, "match_goal", _match_goal)

    target = app.workspace.current.root / "notes.txt"
    result = await controller.run(f'Create a text file at "{target}" with content "hello".')

    assert result.status == "completed"
    assert target.read_text(encoding="utf-8") == "hello"
