from __future__ import annotations

import pytest

from aries.core.tool_id import ToolId
from aries.core.tool_validation import validate_tools
from aries.tools.base import BaseTool, ToolResult


class _WriteToolWithoutPaths(BaseTool):
    name = "write_missing_paths"
    description = "write tool without path params"
    risk_level = "write"
    provider_id = "core"
    provider_version = "test"
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
        },
    }

    async def execute(self, **kwargs: object) -> ToolResult:
        return ToolResult(success=True, content="")


class _LooseMCPTarget(BaseTool):
    name = "loose_mcp"
    description = "loose schema mcp tool"
    risk_level = "write"
    provider_id = "mcp:demo"
    provider_version = "1"
    parameters: dict[str, object] = {}

    async def execute(self, **kwargs: object) -> ToolResult:
        return ToolResult(success=True, content="")


def test_write_tool_with_path_field_requires_path_params() -> None:
    tool = _WriteToolWithoutPaths()
    tool_id = ToolId.from_parts(provider_id="core", tool_name=tool.name)
    result = validate_tools([(tool_id, tool)], strict=True)

    assert any(issue.issue_code == "MISSING_PATH_PARAMS" for issue in result.errors)


def test_mcp_unknown_schema_warns_not_errors() -> None:
    tool = _LooseMCPTarget()
    tool_id = ToolId.from_parts(provider_id="mcp", server_id="demo", tool_name=tool.name)
    result = validate_tools([(tool_id, tool)], strict=True)

    assert any(issue.issue_code == "MISSING_PATH_PARAMS_UNKNOWN_SCHEMA" for issue in result.warnings)
    assert not any(issue.issue_code == "MISSING_PATH_PARAMS_UNKNOWN_SCHEMA" for issue in result.errors)
