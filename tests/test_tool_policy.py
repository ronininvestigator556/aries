from pathlib import Path

import pytest

from aries.cli import Aries
from aries.commands.search import SearchCommand
from aries.config import Config
from aries.core.message import ToolCall
from aries.tools.base import BaseTool, ToolResult


def _bootstrap_config(tmp_path: Path) -> Config:
    profile_dir = tmp_path / "profiles"
    profile_dir.mkdir(parents=True)
    (profile_dir / "default.yaml").write_text("name: default\nsystem_prompt: profile", encoding="utf-8")

    config = Config()
    config.profiles.directory = profile_dir
    config.prompts.directory = tmp_path / "prompts"
    config.workspace.root = tmp_path / "workspaces"
    config.tools.allowed_paths = [tmp_path]
    return config


@pytest.mark.anyio
async def test_policy_denies_disallowed_tool(tmp_path: Path) -> None:
    config = _bootstrap_config(tmp_path)
    config.tools.allow_shell = False
    config.tools.confirmation_required = False

    app = Aries(config)
    tool = app.tool_map["execute_shell"]

    result, audit = await app._run_tool(
        tool,
        ToolCall(id="call-1", name="execute_shell", arguments={"command": "echo hi"}),
    )

    assert not result.success
    assert audit["decision"] == "policy_denied"
    assert result.metadata and result.metadata.get("policy") == "denied"


@pytest.mark.anyio
async def test_confirmation_gate_blocks_on_user_denial(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = _bootstrap_config(tmp_path)
    config.tools.allow_shell = True
    config.tools.confirmation_required = True

    app = Aries(config)
    tool = app.tool_map["write_file"]

    async def _deny(*_: object, **__: object) -> bool:
        return False

    monkeypatch.setattr(app, "_confirm_tool_execution", _deny)

    result, audit = await app._run_tool(
        tool,
        ToolCall(
            id="call-2",
            name="write_file",
            arguments={"path": str(tmp_path / "blocked.txt"), "content": "data"},
        ),
    )

    assert not result.success
    assert audit["decision"] == "user_denied"
    assert result.metadata and result.metadata.get("policy") == "cancelled"


@pytest.mark.anyio
async def test_manual_search_respects_policy_gate(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _bootstrap_config(tmp_path)
    config.tools.allow_network = False
    config.tools.confirmation_required = False
    config.workspace.persist_by_default = True
    config.workspace.default = "demo"

    app = Aries(config)
    search_tool = app.tool_map["search_web"]

    async def _boom(*_: object, **__: object) -> None:
        raise AssertionError("Search tool should be blocked by policy")

    monkeypatch.setattr(search_tool, "execute", _boom)

    cmd = SearchCommand()
    await cmd.execute(app, "blocked query")

    output = capsys.readouterr().out
    assert "Network tools disabled by policy" in output


def test_read_only_tool_skips_confirmation(tmp_path: Path) -> None:
    config = _bootstrap_config(tmp_path)
    app = Aries(config)

    assert not app._requires_confirmation(app.tool_map["read_file"])


class _NetworkOnlyTool(BaseTool):
    name = "custom_net"
    description = "uses network but no shell"
    requires_network = True

    @property
    def parameters(self) -> dict[str, object]:
        return {"type": "object", "properties": {}}

    async def execute(self, **kwargs: object) -> ToolResult:
        return ToolResult(success=True, content="ok")


@pytest.mark.anyio
async def test_attribute_based_policy_blocks_network_tools(tmp_path: Path) -> None:
    config = _bootstrap_config(tmp_path)
    config.tools.allow_network = False
    config.tools.confirmation_required = False
    app = Aries(config)

    tool = _NetworkOnlyTool()
    result, audit = await app._run_tool(
        tool,
        ToolCall(id="net-1", name=tool.name, arguments={}),
    )

    assert not result.success
    assert audit["decision"] == "policy_denied"
    assert result.error and "Network tools disabled by policy" in result.error
