from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from aries.cli import Aries
from aries.config import Config
from aries.core.desktop_ops import DesktopOpsController
from aries.core.message import ToolCall
from aries.providers.base import Provider
from aries.tools.base import BaseTool, ToolResult


class DummyReadTool(BaseTool):
    name = "dummy_read"
    description = "Read-only tool."
    risk_level = "read"
    path_params = ("path",)

    def __init__(self) -> None:
        self._execute_mock = AsyncMock(return_value=ToolResult(success=True, content="ok"))

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        }

    async def execute(self, path: str, **kwargs: object) -> ToolResult:
        return await self._execute_mock(path=path, **kwargs)


class DummyProvider(Provider):
    provider_id = "dummy"
    provider_version = "1.0"

    def __init__(self, tools: list[BaseTool]) -> None:
        self._tools = tools

    def list_tools(self) -> list[BaseTool]:
        return self._tools


@pytest.mark.asyncio
async def test_policy_cache_reuse_for_identical_calls(tmp_path: Path) -> None:
    config = Config()
    config.desktop_ops.enabled = True
    config.desktop_ops.mode = "commander"
    config.workspace.root = tmp_path / "workspaces"

    app = Aries(config)
    app.workspace.new("demo")

    tool = DummyReadTool()
    app.tool_registry.register_provider(DummyProvider([tool]))

    controller = DesktopOpsController(app, mode="commander")
    context = controller._build_context("read file")

    tool_id, tool_ref, error = app._resolve_tool_reference("dummy_read")
    assert error is None
    path = str(app.workspace.current.root / "notes.txt")
    call = ToolCall(id="call-1", name="dummy_read", arguments={"path": path})

    await controller._execute_tool_call_with_policy(context, tool_ref, tool_id, call)
    await controller._execute_tool_call_with_policy(context, tool_ref, tool_id, call)

    policy_entries = [entry for entry in context.audit_log if entry.get("event") == "policy_check"]
    assert len(policy_entries) == 2
    assert policy_entries[1].get("cached") is True
    paths_validated = policy_entries[1].get("paths_validated") or {}
    assert paths_validated["path"].get("cached") is True
