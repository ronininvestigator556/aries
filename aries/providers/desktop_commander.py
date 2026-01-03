"""Desktop Commander MCP provider adapter."""

from __future__ import annotations

import logging
from typing import Iterable

from aries.config import MCPRetryConfig, MCPServerConfig
from aries.providers.mcp import MCPProvider, MCPTool

logger = logging.getLogger(__name__)

_PATH_FIELD_NAMES = {
    "path",
    "paths",
    "file",
    "filename",
    "dest",
    "destination",
    "output",
    "dir",
    "directory",
    "cwd",
    "working_dir",
    "working_directory",
}

_DESKTOP_RISK_LEVELS = {
    "READ_ONLY",
    "WRITE_SAFE",
    "WRITE_DESTRUCTIVE",
    "EXEC_USERSPACE",
    "EXEC_PRIVILEGED",
    "NETWORK",
}


def _normalize_desktop_risk(value: str | None) -> str:
    if not value:
        return "EXEC_USERSPACE"
    normalized = value.strip().upper()
    if normalized in _DESKTOP_RISK_LEVELS:
        return normalized
    return "EXEC_USERSPACE"


def _infer_path_params(schema: dict | None) -> tuple[str, ...]:
    if not isinstance(schema, dict):
        return ()
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return ()
    matches = [name for name in properties if name.lower() in _PATH_FIELD_NAMES]
    return tuple(matches)


def _ensure_schema_is_object(schema: dict | None) -> dict:
    if not isinstance(schema, dict):
        return {"type": "object", "properties": {}}
    if schema.get("type") != "object":
        return {"type": "object", "properties": schema.get("properties", {})}
    if "properties" not in schema:
        schema["properties"] = {}
    return schema


class DesktopCommanderProvider(MCPProvider):
    """Provider adapter that enriches Desktop Commander MCP tools."""

    def __init__(
        self,
        server_config: MCPServerConfig,
        *,
        logger: logging.Logger | None = None,
        retry: MCPRetryConfig | None = None,
        strict: bool = False,
    ) -> None:
        super().__init__(
            server_config,
            logger=logger or logging.getLogger(__name__),
            retry=retry,
            strict=strict,
        )
        self.provider_id = "mcp:desktop"
        self._decorate_tools()

    def _decorate_tools(self) -> None:
        for tool in self._tools:
            self._apply_desktop_metadata(tool)

    def _apply_desktop_metadata(self, tool: MCPTool) -> None:
        definition = getattr(tool, "_definition", None)
        risk = getattr(definition, "risk", None) if definition else None
        desktop_risk = _normalize_desktop_risk(risk)

        schema = _ensure_schema_is_object(getattr(tool, "parameters", None))
        path_params = tool.path_params or _infer_path_params(schema)
        if path_params:
            tool.path_params = path_params
            tool.uses_filesystem_paths = True

        normalized_id = f"mcp.desktop.{tool.name}"
        tool.desktop_risk = desktop_risk
        tool.normalized_id = normalized_id
        if definition is not None:
            tool._definition.parameters = schema

        if desktop_risk == "NETWORK":
            tool.tool_requires_network = True

        if not tool.path_params and tool.uses_filesystem_paths:
            tool.path_params_optional = True

    def list_tools(self) -> list[MCPTool]:
        return list(super().list_tools())


def select_desktop_commander_server(
    servers: Iterable[MCPServerConfig],
    server_id: str,
) -> MCPServerConfig | None:
    for server in servers:
        if server.id == server_id:
            return server
    return None
