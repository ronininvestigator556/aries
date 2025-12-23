from __future__ import annotations

from pathlib import Path

import pytest

from aries.cli import Aries
from aries.config import Config
from aries.core.message import ToolCall


def _make_config(tmp_path: Path) -> Config:
    config = Config()
    config.workspace.root = tmp_path / "workspaces"
    config.workspace.persist_by_default = True
    config.workspace.default = "demo"
    config.profiles.directory = tmp_path / "profiles"
    config.prompts.directory = tmp_path / "prompts"
    config.tools.allowed_paths = [config.workspace.root]
    config.tools.allow_network = True
    config.profiles.directory.mkdir(parents=True, exist_ok=True)
    (config.profiles.directory / "default.yaml").write_text("name: default\nsystem_prompt: base", encoding="utf-8")
    return config


@pytest.mark.anyio
async def test_unknown_arguments_are_rejected(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    app = Aries(config)

    tool_id, tool = app.tool_registry.resolve_with_id("core:read_file")
    call = ToolCall(id="call-1", name=tool_id.qualified, arguments={"path": "note.txt", "extra": "nope"})

    result, audit = await app._run_tool(tool, call, tool_id)

    assert not result.success
    assert "Unknown argument" in (result.error or "")
    assert audit["qualified_tool_id"] == tool_id.qualified
