from __future__ import annotations

import pytest

from aries.cli import Aries
from aries.commands.policy import PolicyCommand
from aries.config import Config, MCPServerConfig
from aries.core.tool_registry import ToolRegistry
from aries.exceptions import ConfigError
from aries.providers.core import CoreProvider
from aries.providers.mcp import (
    MCPClientError,
    MCPProvider,
    MCPToolCallResult,
    MCPToolDefinition,
)


class FakeMCPClient:
    def __init__(
        self,
        server_id: str,
        tools: list[MCPToolDefinition],
        *,
        version: str = "1.0.0",
        fail: bool = False,
    ) -> None:
        self.server_id = server_id
        self._tools = tools
        self._version = version
        self._fail = fail
        self.invocations: list[tuple[str, dict]] = []

    def connect(self) -> None:
        if self._fail:
            raise MCPClientError("connect failed")

    def list_tools(self) -> tuple[list[MCPToolDefinition], str | None]:
        if self._fail:
            raise MCPClientError("list failed")
        return self._tools, self._version

    def invoke(self, tool_name: str, arguments: dict) -> MCPToolCallResult:
        self.invocations.append((tool_name, arguments))
        return MCPToolCallResult(
            success=True,
            content=f"called {tool_name}",
            metadata={"args": arguments},
            artifacts=arguments.get("artifacts"),
        )


def _make_base_config(tmp_path) -> Config:
    config = Config()
    config.workspace.root = tmp_path / "workspaces"
    config.profiles.directory = tmp_path / "profiles"
    config.prompts.directory = tmp_path / "prompts"
    config.tools.allowed_paths = [config.workspace.root]
    config.profiles.directory.mkdir(parents=True, exist_ok=True)
    (config.profiles.directory / "default.yaml").write_text(
        "name: default\nsystem_prompt: base",
        encoding="utf-8",
    )
    return config


def _factory_for(tools: dict[str, list[MCPToolDefinition]], *, fail: bool = False):
    def _factory(server_config: MCPServerConfig) -> FakeMCPClient:
        return FakeMCPClient(server_config.id, tools.get(server_config.id, []), fail=fail)

    return _factory


def test_mcp_disabled_registers_only_core(tmp_path) -> None:
    config = _make_base_config(tmp_path)
    app = Aries(config)

    assert all(not pid.startswith("mcp") for pid in app.tool_registry.providers)
    assert getattr(app, "_mcp_state", []) == []


def test_mcp_connection_failure_warns_when_not_required(tmp_path, monkeypatch) -> None:
    config = _make_base_config(tmp_path)
    config.providers.mcp.enabled = True
    config.providers.mcp.require = False
    config.providers.mcp.servers = [MCPServerConfig(id="stub", url="http://stub")]

    def _raise_client_error(*args, **kwargs):
        raise MCPClientError("boom")

    monkeypatch.setattr("aries.providers.mcp.default_client_factory", _raise_client_error)

    app = Aries(config)

    assert "mcp:stub" in app._warnings_shown
    assert app.tool_registry.providers.get("mcp:stub") is None
    assert any(entry["id"] == "stub" and not entry["connected"] for entry in app._mcp_state)


def test_mcp_connection_failure_honors_required_flag(tmp_path, monkeypatch) -> None:
    config = _make_base_config(tmp_path)
    config.providers.mcp.enabled = True
    config.providers.mcp.require = True
    config.providers.mcp.servers = [MCPServerConfig(id="stub", url="http://stub")]

    def _raise_required_error(*args, **kwargs):
        raise MCPClientError("unavailable")

    monkeypatch.setattr("aries.providers.mcp.default_client_factory", _raise_required_error)

    with pytest.raises(ConfigError) as excinfo:
        Aries(config)

    assert "Failed to initialize MCP server 'stub'" in str(excinfo.value)


def test_registry_registers_mcp_tools_with_provenance() -> None:
    server = MCPServerConfig(id="mcp-local", url="http://stub")
    tools = [
        MCPToolDefinition(
            name="mcp_echo",
            description="echo",
            parameters={"type": "object", "properties": {"text": {"type": "string"}}},
            risk="read",
        )
    ]
    provider = MCPProvider(server, client_factory=_factory_for({"mcp-local": tools}))

    registry = ToolRegistry()
    registry.register_provider(CoreProvider())
    registry.register_provider(provider)

    tool = registry.resolve("mcp_echo")
    assert tool is not None
    assert getattr(tool, "provider_id", "") == "mcp:mcp-local"
    assert getattr(tool, "provider_version", "") == "1.0.0"
    assert getattr(tool, "server_id", "") == "mcp-local"
    assert getattr(tool, "risk_level", "") == "read"


def test_tool_collision_is_actionable() -> None:
    server = MCPServerConfig(id="collision", url="http://stub")
    tools = [
        MCPToolDefinition(
            name="read_file",
            description="conflicts with core",
            parameters={"type": "object", "properties": {}},
            risk="read",
        )
    ]
    provider = MCPProvider(server, client_factory=_factory_for({"collision": tools}))

    registry = ToolRegistry()
    registry.register_provider(CoreProvider())

    with pytest.raises(ValueError) as excinfo:
        registry.register_provider(provider)

    message = str(excinfo.value)
    assert "Tool name collision detected" in message
    assert "read_file" in message
    assert "core" in message
    assert "mcp:collision" in message


@pytest.mark.anyio
async def test_policy_explain_shows_default_exec_for_mcp(tmp_path, monkeypatch, capsys) -> None:
    config = _make_base_config(tmp_path)
    config.providers.mcp.enabled = True
    config.providers.mcp.require = False
    config.providers.mcp.servers = [MCPServerConfig(id="stub", url="http://stub")]

    definitions = [
        MCPToolDefinition(
            name="stub_tool",
            description="no risk provided",
            parameters={"type": "object", "properties": {}},
        )
    ]
    monkeypatch.setattr(
        "aries.providers.mcp.default_client_factory",
        _factory_for({"stub": definitions}),
    )

    app = Aries(config)
    command = PolicyCommand()

    await command.execute(app, "explain stub_tool {}")
    output = capsys.readouterr().out

    assert "mcp:stub" in output
    assert "risk level" in output.lower()
    assert "exec" in output.lower()
