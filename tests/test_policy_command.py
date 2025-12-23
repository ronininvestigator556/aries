from __future__ import annotations

from pathlib import Path

import pytest

from aries.cli import Aries
from aries.commands.policy import PolicyCommand
from aries.config import Config
from aries.exceptions import ConfigError
from aries.providers.core import CoreProvider
from aries.tools.base import BaseTool, ToolResult


def _make_config(tmp_path: Path) -> Config:
    config = Config()
    config.workspace.root = tmp_path / "workspaces"
    config.workspace.persist_by_default = True
    config.workspace.default = "demo"
    config.profiles.directory = tmp_path / "profiles"
    config.prompts.directory = tmp_path / "prompts"
    config.tools.allowed_paths = [config.workspace.root]
    config.profiles.directory.mkdir(parents=True, exist_ok=True)
    (config.profiles.directory / "default.yaml").write_text("name: default\nsystem_prompt: base", encoding="utf-8")
    return config


class _MissingMetadataTool(BaseTool):
    name = "incomplete_tool"
    description = "tool missing required metadata"
    risk_level = ""
    provider_id = "core"
    provider_version = "test"

    @property
    def parameters(self) -> dict[str, object]:
        return {"type": "object", "properties": {}}

    async def execute(self, **kwargs: object) -> ToolResult:
        return ToolResult(success=False, content="")


def _with_incomplete_tool(monkeypatch: pytest.MonkeyPatch) -> _MissingMetadataTool:
    tool = _MissingMetadataTool()
    original = CoreProvider.list_tools

    def _patched(self: CoreProvider) -> list[BaseTool]:
        tools = original(self)
        return [*tools, tool]

    monkeypatch.setattr(CoreProvider, "list_tools", _patched)
    return tool


@pytest.mark.anyio
async def test_policy_show_displays_status(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    config = _make_config(tmp_path)
    config.tools.allow_shell = True
    config.tools.allow_network = True

    app = Aries(config)
    command = PolicyCommand()

    await command.execute(app, "show")

    output = capsys.readouterr().out
    assert "Policy status" in output
    assert "Workspace:" in output
    assert "allow_shell=True" in output
    assert "allow_network=True" in output
    assert "Providers:" in output


@pytest.mark.anyio
async def test_policy_explain_allows_known_tool(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    config = _make_config(tmp_path)
    config.tools.allow_shell = True
    config.tools.allow_network = True

    app = Aries(config)
    command = PolicyCommand()

    await command.execute(app, 'explain read_file {"path":"notes.txt"}')

    output = capsys.readouterr().out
    assert "Policy result:" in output
    assert "ALLOW" in output
    assert "Provider:" in output
    assert "Provider version:" in output
    assert "Confirmation required:" in output


@pytest.mark.anyio
async def test_policy_explain_denies_shell_when_disabled(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    config = _make_config(tmp_path)
    config.tools.allow_shell = False
    config.tools.allow_network = True

    app = Aries(config)
    command = PolicyCommand()

    await command.execute(app, 'explain execute_shell {"command":"echo hi"}')

    output = capsys.readouterr().out
    assert "DENY" in output
    assert "Shell execution disabled by policy" in output


@pytest.mark.anyio
async def test_policy_explain_denies_path_escape(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    config = _make_config(tmp_path)
    config.tools.allow_network = True

    app = Aries(config)
    command = PolicyCommand()

    await command.execute(app, 'explain read_file {"path":"../escape.txt"}')

    output = capsys.readouterr().out
    assert "DENY" in output
    assert "Path validation failed" in output


@pytest.mark.anyio
async def test_policy_explain_marks_confirmation_for_write(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    config = _make_config(tmp_path)
    config.tools.allow_network = True
    config.tools.confirmation_required = True

    app = Aries(config)
    command = PolicyCommand()

    await command.execute(app, 'explain write_file {"path":"note.txt","content":"hi"}')

    output = capsys.readouterr().out
    assert "Confirmation required: yes" in output


@pytest.mark.anyio
async def test_policy_explain_shows_network_semantics(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    config = _make_config(tmp_path)
    config.tools.allow_network = True

    app = Aries(config)
    command = PolicyCommand()

    await command.execute(app, 'explain search_web {"query":"hi"}')

    output = capsys.readouterr().out
    assert "transport=False" in output
    assert "tool=True" in output
    assert "effective=True" in output


@pytest.mark.anyio
async def test_policy_show_reports_inventory_issues(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _with_incomplete_tool(monkeypatch)
    config = _make_config(tmp_path)
    app = Aries(config)
    command = PolicyCommand()

    await command.execute(app, "show")

    output = capsys.readouterr().out
    assert "Inventory" in output
    assert "MISSING_RISK_LEVEL" in output
    assert "incomplete_tool" in output


def test_strict_metadata_blocks_missing_tool(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _with_incomplete_tool(monkeypatch)
    config = _make_config(tmp_path)
    config.providers.strict_metadata = True

    with pytest.raises(ConfigError) as excinfo:
        Aries(config)

    assert "Strict tool metadata enforcement failed" in str(excinfo.value)
    assert "incomplete_tool:MISSING_RISK_LEVEL" in str(excinfo.value)
