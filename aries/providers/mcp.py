"""MCP provider adapter for Aries."""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import subprocess
import time
from dataclasses import dataclass
from typing import Any, Callable, Protocol
from urllib.error import URLError
from urllib.request import Request, urlopen

from aries.config import MCPRetryConfig, MCPServerConfig
from aries.exceptions import ConfigError
from aries.providers.base import Provider
from aries.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)

_MAX_ERROR_LEN = 500


class MCPClientError(Exception):
    """Errors raised by MCP clients."""


class MCPClient(Protocol):
    """Protocol for MCP clients."""

    server_id: str

    def connect(self) -> None:
        """Connect to the MCP server."""

    def list_tools(self) -> tuple[list["MCPToolDefinition"], str | None]:
        """Return available tools and an optional server version."""

    def invoke(self, tool_name: str, arguments: dict[str, Any]) -> "MCPToolCallResult":
        """Invoke a tool."""


@dataclass
class MCPToolDefinition:
    """Description of a tool exposed by an MCP server."""

    name: str
    description: str
    parameters: dict[str, Any]
    risk: str | None = None
    requires_network: bool | None = None
    requires_shell: bool | None = None
    mutates_state: bool | None = None
    emits_artifacts: bool | None = None
    path_params: tuple[str, ...] | None = None
    metadata: dict[str, Any] | None = None


@dataclass
class MCPToolCallResult:
    """Result of invoking an MCP tool."""

    success: bool
    content: str
    error: str | None = None
    metadata: dict[str, Any] | None = None
    artifacts: list[dict[str, Any]] | None = None


class HttpMCPClient:
    """HTTP-based MCP client for servers exposing simple JSON endpoints."""

    def __init__(self, config: MCPServerConfig) -> None:
        if not config.url:
            raise MCPClientError("HTTP MCP client requires a url")
        self.server_id = config.id
        self.base_url = config.url.rstrip("/")
        self.timeout = config.timeout_seconds

    def connect(self) -> None:
        self.list_tools()

    def list_tools(self) -> tuple[list[MCPToolDefinition], str | None]:
        payload = self._request("GET", "/tools")
        tools_raw = payload.get("tools", payload) if isinstance(payload, dict) else payload
        if not isinstance(tools_raw, list):
            raise MCPClientError("Unexpected response from MCP server: missing tools list")

        tools: list[MCPToolDefinition] = []
        for item in tools_raw:
            if not isinstance(item, dict):
                continue
            tools.append(
                MCPToolDefinition(
                    name=str(item.get("name") or ""),
                    description=str(item.get("description") or ""),
                    parameters=item.get("parameters") or {},
                    risk=item.get("risk"),
                    requires_network=item.get("requires_network"),
                    requires_shell=item.get("requires_shell"),
                    mutates_state=item.get("mutates_state"),
                    emits_artifacts=item.get("emits_artifacts"),
                    path_params=tuple(item.get("path_params") or ()),
                    metadata=item.get("metadata") or {},
                )
            )
        version = None
        if isinstance(payload, dict):
            version = payload.get("version") or payload.get("server_version")
        return tools, version

    def invoke(self, tool_name: str, arguments: dict[str, Any]) -> MCPToolCallResult:
        response = self._request("POST", f"/tools/{tool_name}", data={"arguments": arguments})
        if not isinstance(response, dict):
            raise MCPClientError("Unexpected tool response from MCP server")
        return MCPToolCallResult(
            success=bool(response.get("success")),
            content=str(response.get("content") or ""),
            error=str(response.get("error")) if response.get("error") is not None else None,
            metadata=response.get("metadata"),
            artifacts=response.get("artifacts"),
        )

    def _request(self, method: str, path: str, data: dict[str, Any] | None = None) -> Any:
        url = f"{self.base_url}{path}"
        body: bytes | None = None
        headers = {}
        if data is not None:
            body = json.dumps(data).encode("utf-8")
            headers["Content-Type"] = "application/json"
        try:
            request = Request(url=url, data=body, method=method.upper(), headers=headers)
            with urlopen(request, timeout=self.timeout) as resp:
                text = resp.read().decode("utf-8")
            return json.loads(text) if text else {}
        except URLError as exc:  # pragma: no cover - network errors are surfaced to the caller
            raise MCPClientError(str(exc)) from exc
        except json.JSONDecodeError as exc:
            raise MCPClientError(f"Invalid JSON response from MCP server: {exc}") from exc


class CommandMCPClient:
    """Subprocess-based MCP client expecting JSON via command invocations."""

    def __init__(self, config: MCPServerConfig) -> None:
        if not config.command:
            raise MCPClientError("Command MCP client requires a command")
        self.server_id = config.id
        self.command = list(config.command)
        self.env = config.env
        self.timeout = config.timeout_seconds

    def connect(self) -> None:
        # Attempt to list tools as a connectivity probe
        self.list_tools()

    def list_tools(self) -> tuple[list[MCPToolDefinition], str | None]:
        output = self._run(self.command + ["--list-tools"])
        try:
            parsed = json.loads(output)
        except json.JSONDecodeError as exc:
            raise MCPClientError(f"Invalid MCP tool list response: {exc}") from exc
        tools_raw = parsed.get("tools", parsed) if isinstance(parsed, dict) else parsed
        if not isinstance(tools_raw, list):
            raise MCPClientError("Unexpected response from MCP server: missing tools list")

        tools: list[MCPToolDefinition] = []
        for item in tools_raw:
            if not isinstance(item, dict):
                continue
            tools.append(
                MCPToolDefinition(
                    name=str(item.get("name") or ""),
                    description=str(item.get("description") or ""),
                    parameters=item.get("parameters") or {},
                    risk=item.get("risk"),
                    requires_network=item.get("requires_network"),
                    requires_shell=item.get("requires_shell"),
                    mutates_state=item.get("mutates_state"),
                    emits_artifacts=item.get("emits_artifacts"),
                    path_params=tuple(item.get("path_params") or ()),
                    metadata=item.get("metadata") or {},
                )
            )
        version = None
        if isinstance(parsed, dict):
            version = parsed.get("version") or parsed.get("server_version")
        return tools, version

    def invoke(self, tool_name: str, arguments: dict[str, Any]) -> MCPToolCallResult:
        payload = {"tool": tool_name, "arguments": arguments}
        output = self._run(self.command + ["--invoke", tool_name, "--args", json.dumps(payload)])
        try:
            parsed = json.loads(output)
        except json.JSONDecodeError as exc:
            raise MCPClientError(f"Invalid MCP tool response: {exc}") from exc
        if not isinstance(parsed, dict):
            raise MCPClientError("Unexpected tool response from MCP server")
        return MCPToolCallResult(
            success=bool(parsed.get("success")),
            content=str(parsed.get("content") or ""),
            error=str(parsed.get("error")) if parsed.get("error") is not None else None,
            metadata=parsed.get("metadata"),
            artifacts=parsed.get("artifacts"),
        )

    def _run(self, args: list[str]) -> str:
        try:
            proc = subprocess.run(
                args,
                env=self.env or None,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                check=True,
            )
        except subprocess.CalledProcessError as exc:  # pragma: no cover - surfaced to caller
            raise MCPClientError(exc.stderr or exc.stdout or str(exc)) from exc
        return proc.stdout.strip()


def default_client_factory(config: MCPServerConfig) -> MCPClient:
    """Create an MCP client based on server configuration."""
    if config.url:
        return HttpMCPClient(config)
    return CommandMCPClient(config)


class MCPTool(BaseTool):
    """Adapt an MCP tool to the BaseTool contract."""

    def __init__(
        self,
        server_id: str,
        client: MCPClient,
        definition: MCPToolDefinition,
        *,
        provider_id: str,
        provider_version: str,
        warn: Callable[[str, str], None],
        default_transport_requires_network: bool = False,
        default_tool_requires_network: bool = False,
        default_requires_shell: bool = False,
    ) -> None:
        self.server_id = server_id
        self._client = client
        self._definition = definition
        self._warn = warn
        self._on_success: Callable[[], None] | None = None
        self._on_error: Callable[[str], None] | None = None

        self.name = definition.name
        self.description = definition.description
        self.provider_id = provider_id
        self.provider_version = provider_version
        self.risk_level = self._map_risk(definition.risk)
        self.transport_requires_network = default_transport_requires_network
        self.tool_requires_network = (
            bool(definition.requires_network)
            if definition.requires_network is not None
            else default_tool_requires_network
        )
        self.requires_shell = (
            bool(definition.requires_shell)
            if definition.requires_shell is not None
            else default_requires_shell
        )
        self.mutates_state = bool(definition.mutates_state)
        self.emits_artifacts = bool(definition.emits_artifacts)
        self.path_params = tuple(definition.path_params or ())

    @property
    def parameters(self) -> dict[str, Any]:
        return self._definition.parameters or {"type": "object", "properties": {}}

    def _map_risk(self, risk: str | None) -> str:
        if not risk:
            self._warn(f"risk:{self.name}", f"MCP tool '{self.name}' missing risk metadata; defaulting to exec.")
            return "exec"
        normalized = str(risk).lower()
        if normalized in {"read", "write", "exec"}:
            return normalized
        self._warn(
            f"risk:{self.name}",
            f"MCP tool '{self.name}' has unrecognized risk '{risk}'; defaulting to exec.",
        )
        return "exec"

    async def execute(self, **kwargs: Any) -> ToolResult:
        arguments = self._prepare_arguments(kwargs)
        try:
            result = await asyncio.to_thread(self._client.invoke, self.name, arguments)
        except Exception as exc:
            if self._on_error:
                self._on_error(str(exc))
            return ToolResult(success=False, content="", error=str(exc))
        if result.success:
            if self._on_success:
                self._on_success()
        else:
            if self._on_error:
                self._on_error(result.error or "Unknown MCP tool error")
        return ToolResult(
            success=bool(result.success),
            content=result.content,
            error=result.error,
            metadata=result.metadata,
            artifacts=result.artifacts,
        )

    def _prepare_arguments(self, provided: dict[str, Any]) -> dict[str, Any]:
        # Drop Aries-internal hints that remote tools are unlikely to accept.
        filtered = {
            key: value
            for key, value in provided.items()
            if key not in {"workspace", "allowed_paths", "denied_paths"}
        }
        properties = {}
        if isinstance(self.parameters, dict):
            properties = self.parameters.get("properties") or {}

        allowed_keys = set(properties.keys()) if isinstance(properties, dict) else set()
        if allowed_keys:
            unknown = [key for key in filtered if key not in allowed_keys]
            if unknown:
                raise ValueError(
                    f"Unknown argument(s) for MCP tool '{self.name}': {', '.join(sorted(unknown))}"
                )
            return {k: v for k, v in filtered.items() if k in allowed_keys}

        if filtered:
            raise ValueError(
                f"Unknown argument(s) for MCP tool '{self.name}': {', '.join(sorted(filtered))}"
            )
        return {}


def _now() -> dt.datetime:
    return dt.datetime.now(tz=dt.timezone.utc)


@dataclass
class MCPServerStatus:
    """Lifecycle and health information for an MCP server."""

    server_id: str
    transport: str = "unknown"
    state: str = "disconnected"
    last_connect_at: dt.datetime | None = None
    last_success_at: dt.datetime | None = None
    last_error_at: dt.datetime | None = None
    last_error: str | None = None
    tool_count: int = 0

    def note_connect_attempt(self) -> None:
        self.last_connect_at = _now()
        if self.state == "error":
            # keep error state until success
            return
        self.state = "disconnected"

    def mark_connected(self, *, tool_count: int) -> None:
        self.state = "connected"
        self.tool_count = tool_count
        timestamp = _now()
        self.last_success_at = timestamp
        if not self.last_connect_at:
            self.last_connect_at = timestamp
        self.last_error = None
        self.last_error_at = None

    def mark_success(self) -> None:
        self.state = "connected"
        self.last_success_at = _now()

    def mark_error(self, message: str) -> None:
        self.state = "error"
        self.last_error_at = _now()
        self.last_error = (message or "").strip()
        if len(self.last_error) > _MAX_ERROR_LEN:
            self.last_error = self.last_error[:_MAX_ERROR_LEN]


_STATUS_REGISTRY: dict[str, MCPServerStatus] = {}


def register_status(status: MCPServerStatus) -> MCPServerStatus:
    """Store and return a status entry for shared access."""
    _STATUS_REGISTRY[status.server_id] = status
    return status


def get_status(server_id: str) -> MCPServerStatus | None:
    """Return status for a given server id."""
    return _STATUS_REGISTRY.get(server_id)


def snapshot_statuses() -> list[MCPServerStatus]:
    """Return a copy of all known statuses."""
    return list(_STATUS_REGISTRY.values())


def reset_statuses() -> None:
    """Clear all known status entries (intended for tests)."""
    _STATUS_REGISTRY.clear()


class MCPProvider(Provider):
    """Provide tools sourced from MCP servers."""

    def __init__(
        self,
        server_config: MCPServerConfig,
        *,
        client_factory: Callable[[MCPServerConfig], MCPClient] | None = None,
        strict: bool = False,
        logger: logging.Logger | None = None,
        retry: MCPRetryConfig | None = None,
    ) -> None:
        self.server_id = server_config.id
        self.provider_id = f"mcp:{self.server_id}"
        self.provider_version = "unknown"
        self.connected = False
        self.failure_reason: str | None = None
        self._logger = logger or logging.getLogger(__name__)
        self._warned: set[str] = set()
        self._client_factory = client_factory or default_client_factory
        self._client = self._client_factory(server_config)
        self._tools: list[MCPTool] = []
        self._retry = retry or MCPRetryConfig()
        transport = "unknown"
        if server_config.url:
            transport = "http"
        elif server_config.command:
            transport = "command"
        self.status = register_status(
            MCPServerStatus(server_id=self.server_id, transport=transport)
        )
        self._load_tools(server_config, strict=strict)

    def _warn_once(self, key: str, message: str) -> None:
        if key in self._warned:
            return
        self._warned.add(key)
        self._logger.warning(message)

    def _load_tools(self, server_config: MCPServerConfig, *, strict: bool) -> None:
        try:
            tools, version = self._connect_and_list(server_config.id)
        except Exception as exc:
            self.failure_reason = str(exc)
            if strict:
                raise ConfigError(
                    f"Failed to connect to MCP server '{server_config.id}': {exc}"
                ) from exc
            self._logger.warning(
                "MCP server '%s' unavailable; tools will be skipped: %s",
                server_config.id,
                exc,
            )
            self._tools = []
            return

        self.connected = True
        self.provider_version = version or "unknown"
        transport_requires_network = bool(server_config.url)
        requires_shell = bool(server_config.command)

        for tool_def in tools:
            if not tool_def.name:
                self._warn_once(
                    f"toolname:{self.server_id}",
                    "Encountered MCP tool with empty name; skipping",
                )
                continue
            wrapper = MCPTool(
                server_id=self.server_id,
                client=self._client,
                definition=tool_def,
                provider_id=self.provider_id,
                provider_version=self.provider_version,
                warn=self._warn_once,
                default_transport_requires_network=transport_requires_network,
                default_tool_requires_network=False,
                default_requires_shell=requires_shell,
            )
            wrapper._on_success = self._record_success
            wrapper._on_error = self._record_error
            self._tools.append(wrapper)

    def list_tools(self) -> list[BaseTool]:
        return list(self._tools)

    def _connect_and_list(self, server_id: str) -> tuple[list[MCPToolDefinition], str | None]:
        attempts_remaining = max(0, self._retry.attempts)
        last_error: Exception | None = None

        while True:
            self.status.note_connect_attempt()
            try:
                self._client.connect()
                tools, version = self._client.list_tools()
                self.status.mark_connected(tool_count=len(tools))
                return tools, version
            except Exception as exc:
                last_error = exc
                self.status.mark_error(str(exc))
                if attempts_remaining <= 0:
                    raise
                attempts_remaining -= 1
                time.sleep(self._retry.backoff_seconds)

    def _record_success(self) -> None:
        self.status.mark_success()

    def _record_error(self, message: str) -> None:
        self.status.mark_error(message)


__all__ = [
    "MCPClient",
    "MCPClientError",
    "MCPProvider",
    "MCPServerStatus",
    "MCPTool",
    "MCPToolCallResult",
    "MCPToolDefinition",
    "default_client_factory",
    "get_status",
    "register_status",
    "reset_statuses",
    "snapshot_statuses",
]
