from __future__ import annotations

from unittest.mock import AsyncMock
import pytest
from pathlib import Path

from aries.cli import Aries
from aries.config import Config, MCPServerConfig
from aries.core.desktop_ops import DesktopOpsController


@pytest.mark.asyncio
async def test_desktop_ops_halts_on_text_without_tool_call(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = Config()
    config.desktop_ops.enabled = True
    config.desktop_ops.mode = "commander"
    config.workspace.root = tmp_path / "workspaces"
    config.providers.mcp.enabled = True
    config.providers.mcp.servers = [
        MCPServerConfig(id="desktop_commander", command=["dummy"])
    ]

    app = Aries(config)
    app.workspace.new("demo")

    # Mock ollama to return text but no tool calls on step 1, 
    # then return a tool call on step 2 (after nudge), 
    # then DONE on step 3.
    app.ollama.chat = AsyncMock(
        side_effect=[
            # Step 0: Returns a tool call (successful)
            {
                "message": {
                    "tool_calls": [
                        {
                            "id": "call_0",
                            "type": "function",
                            "function": {"name": "mcp:desktop_commander:execute_command", "arguments": {"command": "dir"}},
                        }
                    ]
                }
            },
            # Step 1: Returns text but no tool calls -> should NUDGE
            {
                "message": {
                    "content": "I will now list the files in APIA directory.\n```bash\ncd APIA\n```"
                }
            },
            # Step 2: After nudge, returns a tool call
            {
                "message": {
                    "tool_calls": [
                        {
                            "id": "call_2",
                            "type": "function",
                            "function": {"name": "mcp:desktop_commander:execute_command", "arguments": {"command": "cd APIA && dir"}},
                        }
                    ]
                }
            },
            # Step 3: DONE
            {
                "message": {
                    "content": "DONE: Listed files in APIA"
                }
            }
        ]
    )
    
    # Mock tool execution to succeed
    from aries.tools.base import ToolResult
    app._run_tool = AsyncMock(return_value=(ToolResult(success=True, content="dir output", artifacts=[]), {}))
    # Mock tool resolution
    from unittest.mock import MagicMock
    from dataclasses import dataclass
    @dataclass
    class MockToolId:
        qualified: str
    @dataclass
    class MockTool:
        name: str
        desktop_risk: str | None = None
        risk_level: str = "read"
        qualified_id: str = "mcp:desktop_commander:execute_command"
    
    app._resolve_tool_reference = MagicMock(return_value=(MockToolId("mcp:desktop_commander:execute_command"), MockTool(name="execute_command"), None))

    monkeypatch.setattr("aries.core.desktop_ops.get_user_input", AsyncMock(return_value="y"))

    controller = DesktopOpsController(app, mode="commander")
    result = await controller.run("List files in APIA")

    assert result.status == "completed"
    
    # Check audit log for the nudge
    llm_responses = [entry for entry in result.audit_log if entry["event"] == "llm_response"]
    assert len(llm_responses) == 4
    # Step 1 was the one that triggered the nudge
    assert llm_responses[1]["step"] == 1
    # Step 2 was the nudge response
    assert llm_responses[2]["step"] == 2


@pytest.mark.asyncio
async def test_desktop_ops_stops_after_max_nudges(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = Config()
    config.desktop_ops.enabled = True
    config.desktop_ops.mode = "commander"
    config.workspace.root = tmp_path / "workspaces"
    config.providers.mcp.enabled = True
    config.providers.mcp.servers = [
        MCPServerConfig(id="desktop_commander", command=["dummy"])
    ]

    app = Aries(config)
    app.workspace.new("demo")

    # Mock ollama to return text but no tool calls repeatedly
    app.ollama.chat = AsyncMock(
        return_value={
            "message": {
                "content": "I am just talking and not using tools."
            }
        }
    )
    
    # Mock tool resolution (though it won't be used after nudges start)
    from unittest.mock import MagicMock
    from dataclasses import dataclass
    @dataclass
    class MockToolId:
        qualified: str
    @dataclass
    class MockTool:
        name: str
        desktop_risk: str | None = None
        risk_level: str = "read"
        qualified_id: str = "mcp:desktop_commander:execute_command"
    
    app._resolve_tool_reference = MagicMock(return_value=(MockToolId("mcp:desktop_commander:execute_command"), MockTool(name="execute_command"), None))

    controller = DesktopOpsController(app, mode="commander")
    result = await controller.run("Talk only")

    assert result.status == "stopped"
    
    # Check audit log for the nudges. 
    # Max nudges is 3.
    # Initial attempt (step 0) -> nudge 1
    # Second attempt (step 1) -> nudge 2
    # Third attempt (step 2) -> nudge 3
    # Fourth attempt (step 3) -> halt
    llm_responses = [entry for entry in result.audit_log if entry["event"] == "llm_response"]
    assert len(llm_responses) == 4 
    assert llm_responses[3]["step"] == 3
