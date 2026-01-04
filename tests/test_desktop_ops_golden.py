from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from aries.cli import Aries
from aries.config import Config
from aries.core.desktop_ops import DesktopOpsController
from aries.providers.base import Provider
from aries.tools.base import BaseTool, ToolResult
from tests.helpers.audit import assert_policy_entries_cover_tool_calls, assert_policy_entry_complete
from tests.helpers.transcript import load_episodes


class DummyStartProcessTool(BaseTool):
    name = "start_process"
    description = "Start a dummy process."
    requires_shell = True

    def __init__(self, process_id: str, *, requires_network: bool = False) -> None:
        self._process_id = process_id
        self.tool_requires_network = requires_network

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {"command": {"type": "string"}},
            "required": ["command"],
        }

    async def execute(self, command: str, **kwargs: object) -> ToolResult:
        return ToolResult(
            success=True,
            content=f"started: {command}",
            metadata={"process_id": self._process_id},
        )


class DummyReadProcessTool(BaseTool):
    name = "read_process_output"
    description = "Read dummy process output."
    risk_level = "read"

    def __init__(self, outputs: list[str]) -> None:
        self.outputs = outputs
        self.read_calls = 0

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {"process_id": {"type": "string"}},
            "required": ["process_id"],
        }

    async def execute(self, process_id: str, **kwargs: object) -> ToolResult:
        self.read_calls += 1
        if self.outputs:
            return ToolResult(success=True, content=self.outputs.pop(0))
        return ToolResult(success=True, content="")


class DummyStopProcessTool(BaseTool):
    name = "stop_process"
    description = "Stop dummy process."
    requires_shell = True

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {"process_id": {"type": "string"}},
            "required": ["process_id"],
        }

    async def execute(self, process_id: str, **kwargs: object) -> ToolResult:
        return ToolResult(success=True, content=f"stopped {process_id}")


class DummyWriteTool(BaseTool):
    name = "dummy_write_file"
    description = "Write a file."
    mutates_state = True
    emits_artifacts = True
    risk_level = "write"
    path_params = ("path",)

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
            "required": ["path", "content"],
        }

    async def execute(self, path: str, content: str, **kwargs: object) -> ToolResult:
        return ToolResult(
            success=True,
            content=f"wrote {path}",
            artifacts=[{"path": path, "type": "file", "name": path}],
        )


class DummyPrivilegedTool(BaseTool):
    name = "privileged_command"
    description = "Privileged command."
    desktop_risk = "EXEC_PRIVILEGED"

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {"command": {"type": "string"}},
            "required": ["command"],
        }

    async def execute(self, command: str, **kwargs: object) -> ToolResult:
        return ToolResult(success=True, content=f"ran {command}")


class DummyProvider(Provider):
    provider_id = "dummy"
    provider_version = "1.0"

    def __init__(self, tools: list[BaseTool]) -> None:
        self._tools = tools

    def list_tools(self) -> list[BaseTool]:
        return self._tools


@pytest.mark.asyncio
async def test_desktop_ops_golden_transcript_episodes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    episodes = load_episodes(Path("tests/fixtures/claude_example_convo.txt"))

    for episode in episodes:
        config = Config()
        config.desktop_ops.enabled = True
        config.desktop_ops.mode = "commander"
        config.workspace.root = tmp_path / "workspaces"
        config.desktop_ops.process_poll.max_idle_seconds = 5
        config.desktop_ops.process_poll.max_total_seconds = 0.05
        config.tools.allow_shell = True
        config.tools.confirmation_required = False
        requires_network = "curl" in episode.command
        if requires_network:
            config.tools.allow_network = True

        app = Aries(config)
        app.workspace.new("demo")
        start_tool = DummyStartProcessTool("proc-1", requires_network=requires_network)
        read_tool = DummyReadProcessTool(outputs=list(episode.outputs))
        stop_tool = DummyStopProcessTool()
        write_tool = DummyWriteTool()
        priv_tool = DummyPrivilegedTool()
        app.tool_registry.register_provider(
            DummyProvider([start_tool, read_tool, stop_tool, write_tool, priv_tool])
        )

        artifact_path = str(app.workspace.current.root / "note.txt")
        tool_calls = [
            {
                "id": "call_1",
                "type": "function",
                "function": {
                    "name": "start_process",
                    "arguments": {"command": episode.command},
                },
            }
            ,
            {
                "id": "call_2",
                "type": "function",
                "function": {
                    "name": "dummy_write_file",
                    "arguments": {"path": artifact_path, "content": "hello"},
                },
            },
            {
                "id": "call_3",
                "type": "function",
                "function": {
                    "name": "privileged_command",
                    "arguments": {"command": "sudo -n true"},
                },
            },
        ]

        summary = f"DONE: Commands run: {episode.command}; artifact: {artifact_path}"
        app.ollama.chat = AsyncMock(
            side_effect=[
                {"message": {"tool_calls": tool_calls}},
                {"message": {"content": summary}},
            ]
        )

        user_input = AsyncMock(return_value="y")
        monkeypatch.setattr("aries.core.desktop_ops.get_user_input", user_input)
        monkeypatch.setattr("aries.core.desktop_ops.asyncio.sleep", AsyncMock())

        controller = DesktopOpsController(app, mode="commander")
        result = await controller.run(f"Run episode: {episode.name}")

        assert result.status == "completed"
        assert "Commands executed" in result.summary
        assert "Artifacts" in result.summary
        assert episode.command in result.summary
        assert read_tool.read_calls >= 2
        assert any(
            entry.get("event") == "tool_call" and "start_process" in entry.get("tool", "")
            for entry in result.audit_log
        )
        if episode.outputs:
            assert any(entry.get("event") == "process_output" for entry in result.audit_log)
        assert result.artifacts
        assert artifact_path in result.summary

        policy_entries = [entry for entry in result.audit_log if entry.get("event") == "policy_check"]
        assert any(entry.get("risk") == "NETWORK" for entry in policy_entries) == requires_network
        assert any(entry.get("risk") == "WRITE_DESTRUCTIVE" for entry in policy_entries)
        assert any(entry.get("risk") == "EXEC_PRIVILEGED" for entry in policy_entries)
        assert all(entry.get("approval_required") for entry in policy_entries if entry.get("risk") in {"NETWORK", "WRITE_DESTRUCTIVE", "EXEC_PRIVILEGED"})
        for entry in policy_entries:
            assert_policy_entry_complete(entry)

        tool_calls = [entry for entry in result.audit_log if entry.get("event") == "tool_call"]
        assert_policy_entries_cover_tool_calls(policy_entries, tool_calls)

        if episode.outputs == []:
            assert any(entry.get("event") == "process_stalled" for entry in result.audit_log)
            assert any(entry.get("event") == "process_stop" for entry in result.audit_log)

        if requires_network:
            assert user_input.call_count >= 1
