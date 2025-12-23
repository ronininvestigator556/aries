"""Tool metadata validation for policy inventory and strict startup checks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Literal, Sequence

from aries.core.tool_id import ToolId
from aries.core.tool_registry import ToolRegistry
from aries.tools.base import BaseTool

_ALLOWED_RISK = {"READ", "WRITE", "EXEC"}
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
}


@dataclass
class ToolValidationIssue:
    """Describes a tool metadata gap."""

    severity: Literal["WARN", "ERROR"]
    qualified_tool_id: str
    provider_id: str
    server_id: str
    issue_code: str
    message: str


@dataclass
class ToolValidationResult:
    """Container for validation issues."""

    warnings: list[ToolValidationIssue]
    errors: list[ToolValidationIssue]

    @property
    def all_issues(self) -> list[ToolValidationIssue]:
        """Return all issues regardless of severity."""
        return [*self.warnings, *self.errors]


def validate_tools(
    registry_or_items: ToolRegistry | Iterable[tuple[ToolId, BaseTool]],
    *,
    strict: bool = False,
) -> ToolValidationResult:
    """Validate tools and return warnings/errors.

    Args:
        registry_or_items: Tool registry or iterable of (ToolId, BaseTool).
        strict: Whether issues should be escalated to errors where applicable.
    """
    items = (
        registry_or_items.items()
        if isinstance(registry_or_items, ToolRegistry)
        else list(registry_or_items)
    )

    warnings: list[ToolValidationIssue] = []
    errors: list[ToolValidationIssue] = []

    for tool_id, tool in items:
        for issue in _validate_tool(tool_id, tool, strict=strict):
            if issue.severity == "ERROR":
                errors.append(issue)
            else:
                warnings.append(issue)

    return ToolValidationResult(warnings=warnings, errors=errors)


def _validate_tool(tool_id: ToolId, tool: BaseTool, *, strict: bool) -> list[ToolValidationIssue]:
    issues: list[ToolValidationIssue] = []
    provider_id = getattr(tool, "provider_id", "") or ""
    server_id = getattr(tool, "server_id", "") or ""

    if not provider_id:
        issues.append(
            _issue(
                tool_id,
                provider_id,
                server_id,
                "MISSING_PROVIDER_ID",
                "Provider provenance missing (provider_id).",
                strict=strict,
            )
        )
    if not getattr(tool, "provider_version", ""):
        issues.append(
            _issue(
                tool_id,
                provider_id,
                server_id,
                "MISSING_PROVIDER_VERSION",
                "Provider provenance missing (provider_version).",
                strict=strict,
            )
        )

    risk = _normalize_risk(getattr(tool, "risk_level", None))
    if not risk:
        issues.append(
            _issue(
                tool_id,
                provider_id,
                server_id,
                "MISSING_RISK_LEVEL",
                "risk_level is required (READ|WRITE|EXEC).",
                strict=strict,
            )
        )
    elif risk not in _ALLOWED_RISK:
        issues.append(
            _issue(
                tool_id,
                provider_id,
                server_id,
                "INVALID_RISK_LEVEL",
                f"risk_level '{risk}' is not one of READ|WRITE|EXEC.",
                strict=strict,
            )
        )

    emits_artifacts = getattr(tool, "emits_artifacts", None)
    if emits_artifacts is None:
        issues.append(
            _issue(
                tool_id,
                provider_id,
                server_id,
                "MISSING_EMITS_ARTIFACTS",
                "emits_artifacts must be declared (true/false).",
                strict=strict,
            )
        )
    elif not isinstance(emits_artifacts, bool):
        issues.append(
            _issue(
                tool_id,
                provider_id,
                server_id,
                "INVALID_EMITS_ARTIFACTS",
                "emits_artifacts must be a boolean.",
                strict=strict,
            )
        )

    if not _has_network_metadata(tool):
        issues.append(
            _issue(
                tool_id,
                provider_id,
                server_id,
                "MISSING_NETWORK_METADATA",
                "Declare transport_requires_network/tool_requires_network or requires_network.",
                strict=strict,
            )
        )

    issues.extend(
        _path_param_issues(
            tool_id,
            tool,
            provider_id=provider_id,
            server_id=server_id,
            strict=strict,
        )
    )

    return issues


def _path_param_issues(
    tool_id: ToolId,
    tool: BaseTool,
    *,
    provider_id: str,
    server_id: str,
    strict: bool,
) -> list[ToolValidationIssue]:
    issues: list[ToolValidationIssue] = []
    path_params: Sequence[str] = getattr(tool, "path_params", ()) or ()
    path_params_optional = bool(getattr(tool, "path_params_optional", False))
    uses_filesystem = bool(getattr(tool, "uses_filesystem_paths", False))

    fields, schema_unknown = _extract_schema_fields(getattr(tool, "parameters", None))
    matched_fields = sorted(fields & _PATH_FIELD_NAMES)
    risk = _normalize_risk(getattr(tool, "risk_level", None))
    requires_path_params = False

    if uses_filesystem:
        requires_path_params = True
    elif risk in {"WRITE", "EXEC"} and matched_fields:
        requires_path_params = True

    if requires_path_params and not path_params and not path_params_optional:
        if provider_id.startswith("mcp") and schema_unknown and not uses_filesystem:
            issues.append(
                _issue(
                    tool_id,
                    provider_id,
                    server_id,
                    "MISSING_PATH_PARAMS_UNKNOWN_SCHEMA",
                    "Path-like fields or schema unknown; declare path_params to avoid filesystem ambiguity.",
                    strict=strict,
                    enforce_strict=False,
                )
            )
        else:
            rule_hint = "uses_filesystem_paths=True" if uses_filesystem else f"fields={','.join(matched_fields)}"
            issues.append(
                _issue(
                    tool_id,
                    provider_id,
                    server_id,
                    "MISSING_PATH_PARAMS",
                    f"Declare path_params for filesystem-related tool ({rule_hint}).",
                    strict=strict,
                )
            )
    elif (
        provider_id.startswith("mcp")
        and schema_unknown
        and not path_params
        and not path_params_optional
        and risk in {"WRITE", "EXEC"}
    ):
        issues.append(
            _issue(
                tool_id,
                provider_id,
                server_id,
                "MISSING_PATH_PARAMS_UNKNOWN_SCHEMA",
                "MCP tool has unknown/loose schema; declare path_params when writing/exec to avoid path misuse.",
                strict=strict,
                enforce_strict=False,
            )
        )

    return issues


def _extract_schema_fields(parameters: object) -> tuple[set[str], bool]:
    if not isinstance(parameters, dict):
        return set(), True
    properties = parameters.get("properties")
    if not isinstance(properties, dict):
        return set(), True
    if not properties:
        return set(), True
    return {str(key).lower() for key in properties}, False


def _has_network_metadata(tool: BaseTool) -> bool:
    transport = getattr(tool, "transport_requires_network", None)
    tool_requires = getattr(tool, "tool_requires_network", None)
    requires = getattr(tool, "requires_network", None)

    explicit_flags = isinstance(transport, bool) and isinstance(tool_requires, bool)
    consolidated_flag = isinstance(requires, bool)
    return bool(explicit_flags or consolidated_flag)


def _normalize_risk(risk: object) -> str | None:
    if risk is None:
        return None
    value = str(risk).strip()
    return value.upper() if value else None


def _issue(
    tool_id: ToolId,
    provider_id: str,
    server_id: str,
    issue_code: str,
    message: str,
    *,
    strict: bool,
    enforce_strict: bool = True,
    severity: Literal["WARN", "ERROR"] = "WARN",
) -> ToolValidationIssue:
    level: Literal["WARN", "ERROR"] = severity
    if severity == "WARN" and strict and enforce_strict:
        level = "ERROR"
    return ToolValidationIssue(
        severity=level,
        qualified_tool_id=getattr(tool_id, "qualified", str(tool_id)),
        provider_id=provider_id,
        server_id=server_id,
        issue_code=issue_code,
        message=message,
    )
