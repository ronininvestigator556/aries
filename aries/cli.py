"""
Main CLI loop and command routing for Aries.

This module handles:
- User input processing
- Command parsing and routing
- Chat message handling
- Main application loop
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Any

MIN_PYTHON = (3, 11)
MAX_PYTHON = (3, 14)


def _ensure_supported_python(version_info: Any | None = None) -> None:
    """Ensure the interpreter is within the supported range.

    Args:
        version_info: Optional version tuple-like object; defaults to ``sys.version_info``.

    Raises:
        RuntimeError: When the interpreter is outside the supported range.
    """

    info = version_info or sys.version_info
    major = getattr(info, "major", None)
    minor = getattr(info, "minor", None)
    micro = getattr(info, "micro", 0)
    current = (int(major), int(minor), int(micro))

    if current < MIN_PYTHON or current >= MAX_PYTHON:
        detected = ".".join(str(part) for part in current[:3])
        raise RuntimeError(
            "Unsupported Python version: "
            f"{detected}. ARIES requires Python 3.11-3.13. "
            "Install Python 3.11, 3.12, or 3.13 and/or use the project virtual environment."
        )


_ensure_supported_python()

import asyncio
import hashlib
import logging
import re
import time
import uuid
from pathlib import Path
from typing import Iterable

from rich.console import Console

from aries.commands import get_command, is_command
from aries.config import Config, load_config
from aries.core.conversation import Conversation
from aries.core.message import ToolCall
from aries.core.ollama_client import OllamaClient
from aries.core.tool_policy import ToolPolicy
from aries.core.tool_registry import AmbiguousToolError, ToolRegistry
from aries.core.profile import Profile, ProfileManager
from aries.core.workspace import (
    ArtifactRef,
    TranscriptEntry,
    WorkspaceManager,
    resolve_and_validate_path,
)
from aries.exceptions import FileToolError
from aries.core.tool_validation import validate_tools
from aries.core.tokenizer import TokenEstimator
from aries.exceptions import AriesError, ConfigError
from aries.providers import CoreProvider, MCPProvider, DesktopCommanderProvider
from aries.providers.builtin import BuiltinProvider
from aries.providers.desktop_commander import select_desktop_commander_server
from aries.providers.mcp import MCPServerStatus, register_status
from aries.tools.base import BaseTool, ToolResult
from aries.ui.display import display_error, display_info, display_warning, display_welcome
from aries.ui.input import get_user_input

if TYPE_CHECKING:
    from aries.rag.indexer import Indexer
    from aries.rag.retriever import Retriever


console = Console()
logger = logging.getLogger(__name__)

# Internal classification constants
EMPTY_ASSISTANT_RESPONSE = "empty_assistant_response"
TOOL_CALL_PARSE_ERROR = "tool_call_parse_error"
TOOL_CALL_INVALID_ARGUMENTS = "tool_call_invalid_arguments"
NON_ACTIONABLE_RESPONSE = "non_actionable_response"


class Aries:
    """Main Aries application class."""

    def __init__(self, config: Config) -> None:
        """Initialize Aries.

        Args:
            config: Application configuration.
        """
        self.config = config
        self._warnings_shown: set[str] = set()
        self.tool_registry = ToolRegistry()
        if getattr(config.providers, "builtin", None) is None or config.providers.builtin.enabled:
            self.tool_registry.register_provider(BuiltinProvider())
        self.tool_registry.register_provider(CoreProvider())
        self._mcp_state: list[dict[str, Any]] = []
        self._register_mcp_providers()
        self._register_desktop_commander_provider()
        strict_metadata = bool(getattr(config.providers, "strict_metadata", False))
        self.tool_validation = validate_tools(self.tool_registry, strict=strict_metadata)
        if strict_metadata and self.tool_validation.errors:
            self._raise_strict_metadata_error(config.providers.strict_metadata_max_issues)
        self.tools: list[BaseTool] = self.tool_registry.list_tools()
        self.tool_definitions = self.tool_registry.list_tool_definitions(qualified=True)
        self.tool_map: dict[str, BaseTool] = self.tool_registry.lookup_map()
        self._token_estimator = TokenEstimator(
            mode=config.tokens.mode,
            encoding=config.tokens.encoding,
            approx_chars_per_token=config.tokens.approx_chars_per_token,
        )
        self.profiles = ProfileManager(config.profiles.directory)
        self.tool_policy = ToolPolicy(config.tools)
        self.workspace = WorkspaceManager(config.workspace, config.tools)
        self.ollama = OllamaClient(config.ollama)
        self.indexer: "Indexer | None" = None
        self.retriever: "Retriever | None" = None
        self._rag_import_error: Exception | None = None
        self.running = True
        self.current_model: str = config.ollama.default_model
        self.current_rag: str | None = None
        self.desktop_ops_mode: str = getattr(config.desktop_ops, "mode", "guide")
        self.desktop_ops_state: dict[str, Any] = {
            "cwd": None,
            "recipe": None,
            "active_processes": 0,
        }
        self.conversation_id = str(uuid.uuid4())
        self._rag_retrieval_attempted: bool = False

        default_profile = self._resolve_default_profile()
        self.conversation = Conversation(
            system_prompt=None,
            max_context_tokens=config.conversation.max_context_tokens,
            max_messages=config.conversation.max_messages,
            encoding=config.conversation.encoding,
            token_estimator=self._token_estimator,
        )
        self._apply_profile(default_profile)
        self._initialize_default_workspace()

        # Phase A: Console State
        self.last_action_summary: str = "Ready"
        self.last_action_details: dict[str, Any] | None = None
        self.last_action_status: str = "Idle"
        self.last_model_turn: dict[str, Any] | None = None
        self.next_input_default: str = ""
        self.processing_task: asyncio.Task | None = None
        self.last_policy_trace: dict[str, Any] | None = None

        # Phase B: Agent Runs
        self.current_run = None
        self.run_manager = None

    def _get_status_bar(self) -> Any:
        """Generate status bar content."""
        from prompt_toolkit.formatted_text import HTML
        
        ws = self.workspace.current.name if self.workspace.current else "default"
        model = self.current_model
        profile = self.current_prompt or "default"
        rag = f"RAG:{self.current_rag}" if self.current_rag else "RAG:off"
        status = self.last_action_status
        last_action = self.last_action_summary
        desktop_mode = ""
        if getattr(self.config, "desktop_ops", None) and self.config.desktop_ops.enabled:
            cwd = self.desktop_ops_state.get("cwd") or str(Path.cwd())
            recipe = self.desktop_ops_state.get("recipe") or "-"
            processes = self.desktop_ops_state.get("active_processes", 0)
            desktop_mode = (
                f" | <b>DesktopOps:</b> {self.desktop_ops_mode} cwd={cwd} recipe={recipe} procs={processes}"
            )
        
        # Add run status if active
        run_status = ""
        if self.current_run:
            from aries.core.agent_run import RunStatus
            if self.current_run.status in (
                RunStatus.RUNNING, RunStatus.PLANNING, RunStatus.PAUSED, RunStatus.AWAITING_APPROVAL
            ):
                mode = "manual" if getattr(self.current_run, "manual_stepping", False) else "auto"
                run_status = f" | <b>Run:</b> {self.current_run.status.value} ({mode})"
                if self.current_run.current_step_index < len(self.current_run.plan):
                    run_status += f" (Step {self.current_run.current_step_index + 1}/{len(self.current_run.plan)})"
        
        return HTML(
            f" <b>WS:</b> {ws} | <b>Model:</b> {model} | <b>Profile:</b> {profile} | <b>{rag}</b> | {status} | <i>{last_action}</i>{run_status}{desktop_mode}"
        )

    def _warn_once(self, key: str, message: str) -> None:
        """Emit a warning message once per key."""
        if key in self._warnings_shown:
            return
        display_warning(message)
        self._warnings_shown.add(key)

    def _ensure_rag_components(self) -> bool:
        """Initialize optional RAG components without forcing heavy dependencies."""
        if self.indexer and self.retriever:
            return True
        if self._rag_import_error:
            return False
        try:
            from aries.rag.indexer import Indexer
            from aries.rag.retriever import Retriever
        except Exception as exc:  # pragma: no cover - environment-specific imports
            self._rag_import_error = exc
            self.indexer = None
            self.retriever = None
            return False

        self.indexer = Indexer(
            self.config.rag, self.ollama, token_estimator=self._token_estimator
        )
        self.retriever = Retriever(self.config.rag, self.ollama)
        if self.workspace.current:
            self._apply_workspace_index_path()
        return True

    def rag_dependency_message(self) -> str:
        """Return a user-friendly message for missing RAG extras."""
        base = "RAG features require optional dependencies. Install with `pip install -e \".[rag]\"`."
        if self._rag_import_error:
            base = f"{base} ({self._rag_import_error})"
        return base

    def _register_mcp_providers(self) -> None:
        """Register MCP providers when enabled."""
        mcp_cfg = getattr(self.config, "providers", None)
        if not mcp_cfg or not getattr(mcp_cfg, "mcp", None):
            return
        mcp_settings = mcp_cfg.mcp
        if not mcp_settings.enabled:
            return

        if not mcp_settings.servers:
            self._warn_once(
                "mcp:no_servers",
                "MCP provider enabled but no servers configured; skipping.",
            )
            return

        for server in mcp_settings.servers:
            desktop_cfg = getattr(self.config, "desktop_ops", None)
            if desktop_cfg and desktop_cfg.enabled and server.id == desktop_cfg.server_id:
                continue
            try:
                provider = MCPProvider(server, strict=mcp_settings.require, retry=mcp_settings.retry)
            except ConfigError:
                # Already contextualized; re-raise for startup failure
                raise
            except Exception as exc:
                if mcp_settings.require:
                    raise ConfigError(
                        f"Failed to initialize MCP server '{server.id}': {exc}"
                    ) from exc
                status = MCPServerStatus(server_id=server.id)
                status.mark_error(str(exc))
                register_status(status)
                self._warn_once(
                    f"mcp:{server.id}",
                    f"MCP server '{server.id}' unavailable; tools will be skipped ({exc}).",
                )
                self._mcp_state.append(self._status_summary(status))
                continue

            self.tool_registry.register_provider(provider)
            self._mcp_state.append(self._status_summary(provider.status))

            if not provider.connected and not mcp_settings.require:
                reason = provider.failure_reason or "connection unavailable"
                self._warn_once(
                    f"mcp:{server.id}:disconnected",
                    f"MCP server '{server.id}' unavailable; tools skipped ({reason}).",
                )

    def _register_desktop_commander_provider(self) -> None:
        desktop_cfg = getattr(self.config, "desktop_ops", None)
        if not desktop_cfg or not desktop_cfg.enabled:
            return
        providers_cfg = getattr(self.config, "providers", None)
        mcp_cfg = getattr(providers_cfg, "mcp", None) if providers_cfg else None
        builtin_enabled = bool(getattr(getattr(providers_cfg, "builtin", None), "enabled", False))
        servers = mcp_cfg.servers if mcp_cfg else []
        server = select_desktop_commander_server(servers, desktop_cfg.server_id)
        if not server:
            if builtin_enabled:
                return
            self._warn_once(
                "desktop_ops:no_server",
                (
                    f"Desktop Ops enabled but MCP server '{desktop_cfg.server_id}' not configured. "
                    "Desktop Ops requires a configured provider (desktop_commander or filesystem). "
                    "Configure in config.yaml. Expected keys: providers.mcp.enabled, "
                    "providers.mcp.servers[].id, command or url. Example (Windows): "
                    "providers:\n  mcp:\n    enabled: true\n    servers:\n      - id: desktop_commander\n"
                    "        command: [\"powershell\", \"-NoLogo\", \"-NoProfile\", \"-Command\", \"desktop-commander\"]"
                ),
            )
        try:
            provider = DesktopCommanderProvider(
                server,
                retry=mcp_cfg.retry if mcp_cfg else None,
                strict=bool(getattr(providers_cfg, "strict_metadata", False)),
            )
        except Exception as exc:
            raise ConfigError(
                f"Desktop Ops requires MCP server '{server.id}'. "
                "Binary not found or not executable."
            ) from exc
        self.tool_registry.register_provider(provider)

    def _status_summary(self, status: MCPServerStatus) -> dict[str, Any]:
        return {
            "id": status.server_id,
            "provider_id": f"mcp:{status.server_id}",
            "provider_version": getattr(status, "provider_version", "unknown"),
            "connected": status.state == "connected",
            "state": status.state,
            "transport": status.transport,
            "tools": status.tool_count,
            "last_connect_at": status.last_connect_at,
            "last_success_at": status.last_success_at,
            "last_error_at": status.last_error_at,
            "last_error": status.last_error,
        }

    def _raise_strict_metadata_error(self, max_issues: int) -> None:
        limit = max(1, max_issues or 25)
        preview = self.tool_validation.errors[:limit]
        details = "; ".join(f"{issue.qualified_tool_id}:{issue.issue_code}" for issue in preview)
        remaining = len(self.tool_validation.errors) - limit
        if remaining > 0:
            details += f"; ... {remaining} more"
        raise ConfigError(
            "Strict tool metadata enforcement failed: "
            f"{len(self.tool_validation.errors)} issue(s) detected "
            f"({details}). Resolve metadata and restart, or run /policy show --verbose to inspect. "
            "Disable providers.strict_metadata to bypass enforcement."
        )

    def _resolve_default_profile(self) -> Profile:
        """Load the default profile with legacy fallback enabled."""
        allow_legacy = not self.config.profiles.require
        return self._load_profile(
            self.config.profiles.default,
            allow_legacy_prompt=allow_legacy,
            require_profile=self.config.profiles.require,
        )

    def _load_profile(
        self,
        name: str,
        *,
        allow_legacy_prompt: bool = False,
        require_profile: bool = False,
    ) -> Profile:
        """Load a profile with optional legacy prompt fallback.

        Args:
            name: Profile name to load.
            allow_legacy_prompt: Whether to fall back to prompts/<name>.md if missing.
            require_profile: Whether profile presence is mandatory.

        Raises:
            ConfigError: If the profile cannot be resolved.
        """
        try:
            return self.profiles.load(name)
        except FileNotFoundError:
            if require_profile:
                raise ConfigError(
                    f"Profile '{name}' is required but was not found. "
                    "Create the profile under the profiles directory or disable profiles.require."
                )

            legacy = self._load_legacy_prompt(name, allow_legacy_prompt)
            if legacy:
                return legacy

            if allow_legacy_prompt and name == "researcher":
                self._warn_once(
                    f"researcher_fallback:{name}",
                    "No default profile configured; using built-in 'researcher' profile with no prompt.",
                )
                return Profile(name="researcher", description="Built-in default", system_prompt=None)

            available = self.profiles.list()
            available_msg = ", ".join(available) if available else "none found"
            raise ConfigError(
                f"Profile '{name}' not found. Available profiles: {available_msg}. "
                "Create the profile under the profiles directory or update config.profiles.default."
            )

    def _load_legacy_prompt(self, name: str, allow_legacy_prompt: bool) -> Profile | None:
        """Load a legacy markdown prompt when allowed."""
        if not allow_legacy_prompt:
            return None

        prompt_path = Path(self.config.prompts.directory) / f"{name}.md"
        if not prompt_path.exists():
            return None

        self._warn_once(
            f"legacy_prompt:{name}",
            f"Profile '{name}' not found; using legacy prompt file at {prompt_path}. "
            "Create a profile YAML to silence this warning.",
        )
        prompt_text = prompt_path.read_text(encoding="utf-8")
        return Profile(name=name, description="Legacy prompt", system_prompt=prompt_text)

    def _apply_profile(self, profile: Profile) -> None:
        """Apply a profile to the current conversation and tool policy."""
        self.conversation.set_system_prompt(profile.system_prompt)
        if profile.tool_policy is not None:
            if "allow_shell" in profile.tool_policy:
                self.tool_policy.config.allow_shell = bool(profile.tool_policy["allow_shell"])
            if "allow_network" in profile.tool_policy:
                self.tool_policy.config.allow_network = bool(profile.tool_policy["allow_network"])
        self.current_prompt = profile.name

    def _initialize_default_workspace(self) -> None:
        """Open or create the default workspace when configured."""
        workspace_cfg = self.config.workspace
        if not (workspace_cfg.persist_by_default and workspace_cfg.default):
            return
        try:
            self.workspace.open(workspace_cfg.default)
        except FileNotFoundError:
            self.workspace.new(workspace_cfg.default)
        self._apply_workspace_index_path()

    async def _check_incomplete_runs(self) -> None:
        """C.6 - Check for incomplete runs and offer recovery options."""
        if not self.workspace.current:
            return

        # Initialize run manager
        if not hasattr(self, "run_manager"):
            self.run_manager = RunManager(self.workspace.current.root)

        from aries.core.agent_run import RunStatus
        incomplete_runs = []
        for run_id in self.run_manager.list_runs():
            run = self.run_manager.load_run(run_id)
            if not run:
                continue

            # Check if incomplete (not completed, failed, stopped, cancelled, or archived)
            if run.status in (
                RunStatus.RUNNING, RunStatus.PLANNING, RunStatus.PAUSED, RunStatus.AWAITING_APPROVAL
            ):
                # Skip archived runs
                if hasattr(run, "archived") and run.archived:
                    continue
                incomplete_runs.append(run)

        if incomplete_runs:
            from aries.ui.display import display_warning
            from aries.ui.input import get_user_input

            console.print(f"\n[yellow]Found {len(incomplete_runs)} incomplete run(s):[/yellow]")
            for run in incomplete_runs:
                duration = run.duration_seconds()
                duration_str = f"{duration:.1f}s" if duration else "N/A"
                console.print(f"  - {run.run_id}: {run.goal} (Status: {run.status.value}, Duration: {duration_str})")

            console.print("\nOptions:")
            console.print("  [i]inspect[/i] <run_id> - Inspect a run")
            console.print("  [i]resume[/i] <run_id> - Resume a paused run")
            console.print("  [i]archive[/i] <run_id> - Archive a run")
            console.print("  [i]skip[/i] - Continue without action")

            response = await get_user_input("\nAction (or 'skip'): ")
            response = response.strip().lower()

            if response.startswith("inspect "):
                run_id = response.split(maxsplit=1)[1]
                from aries.commands.run import RunCommand
                cmd = RunCommand()
                await cmd._handle_inspect(self, run_id)
            elif response.startswith("resume "):
                run_id = response.split(maxsplit=1)[1]
                from aries.commands.run import RunCommand
                cmd = RunCommand()
                await cmd._handle_resume_by_id(self, run_id)
            elif response.startswith("archive "):
                run_id = response.split(maxsplit=1)[1]
                from aries.commands.run import RunCommand
                cmd = RunCommand()
                await cmd._handle_archive(self, run_id)
            # else skip - continue normally

    def _resolve_tool_reference(self, name: str) -> tuple[Any, Any, str | None]:
        """Resolve a tool name to a tool object and tool id with error messaging."""
        try:
            resolved = self.tool_registry.resolve_with_id(name)
        except AmbiguousToolError as exc:
            options = ", ".join(sorted(c.qualified for c in exc.candidates))
            return None, None, f"Tool '{name}' is ambiguous. Try one of: {options}"

        if not resolved:
            known = ", ".join(sorted(self.tool_registry.tools))
            return None, None, f"Unknown tool: {name}. Known tools: {known}"

        tool_id, tool = resolved
        return tool_id, tool, None

    def _requires_confirmation(self, tool: BaseTool) -> bool:
        """Determine whether a tool should require confirmation."""
        risk = str(getattr(tool, "risk_level", "read")).lower()
        if getattr(tool, "mutates_state", False):
            return True
        return risk in {"write", "exec"}

    def _sanitize_arguments(self, args: dict[str, Any]) -> dict[str, Any]:
        """Sanitize tool arguments for logging."""
        sanitized: dict[str, Any] = {}
        for key, value in args.items():
            if key == "env" and isinstance(value, dict):
                sanitized[key] = {"__keys__": sorted(str(k) for k in value.keys())}
                continue
            if isinstance(value, str):
                sanitized[key] = value if len(value) <= 200 else value[:200] + "...[truncated]"
            else:
                sanitized[key] = value
        return sanitized

    def _validate_tool_arguments(self, tool: BaseTool, args: dict[str, Any]) -> dict[str, Any]:
        """Validate tool arguments against declared schema."""
        schema = getattr(tool, "parameters", {}) or {}
        properties = schema.get("properties") if isinstance(schema, dict) else {}
        allowed_keys = set(properties.keys()) if isinstance(properties, dict) else set()
        required_fields = schema.get("required") if isinstance(schema, dict) else []
        if not isinstance(required_fields, (list, tuple)):
            required_fields = []
        required_fields = [field for field in required_fields if isinstance(field, str) and field]

        # Check for unknown keys
        unknown = [key for key in args if key not in allowed_keys and key != "__raw_arguments"]
        if unknown:
            allowed_display = ", ".join(sorted(allowed_keys)) if allowed_keys else "none declared"
            raise ValueError(
                f"Unknown argument(s) for tool '{getattr(tool, 'qualified_id', tool.name)}': "
                f"{', '.join(sorted(unknown))}. Allowed keys: {allowed_display}"
            )

        if required_fields:
            # Enforce only explicitly-declared required fields; empty schemas allow empty args
            missing = []
            for field in required_fields:
                if field not in args:
                    missing.append(field)
                    continue
                value = args.get(field)
                if value is None:
                    missing.append(field)
                elif isinstance(value, str) and not value.strip():
                    missing.append(field)
            if missing:
                raise ValueError(
                    f"Missing required argument(s) for tool '{getattr(tool, 'qualified_id', tool.name)}': "
                    f"{', '.join(sorted(missing))}"
                )

        if not allowed_keys:
            return dict(args)
        return {k: v for k, v in args.items() if k in allowed_keys}

    def _hash_output(self, text: str) -> tuple[str | None, int]:
        """Hash output content with a bounded sample."""
        if not text:
            return None, 0
        encoded = text.encode("utf-8")
        sample = encoded[:4096]
        return hashlib.sha256(sample).hexdigest(), len(encoded)

    def _truncate_output(self, text: str, limit: int = 2000) -> tuple[str, bool]:
        """Truncate long tool output for transcripts."""
        if len(text) <= limit:
            return text, False
        return text[:limit] + f"\n... (truncated, {len(text)} total chars)", True

    def _is_non_actionable_response(self, content: str, *, tool_calls_present: bool = False) -> bool:
        """Heuristic to detect acknowledgments that do not reflect actionable output."""
        if tool_calls_present:
            return False

        text = (content or "").strip()
        if not text:
            return False
        if len(text) > 40:
            return False

        if re.search(r"^[\s]*[-*•#]", text, re.MULTILINE):
            return False
        if re.search(r"\d", text):
            return False
        if re.search(r"(?:/|\\)\\S", text):
            return False

        lowered = text.lower()
        verbs = ("created", "saved", "found", "updated", "wrote", "generated", "executed")
        if any(verb in lowered for verb in verbs):
            return False

        cleaned = re.sub(r"[^\w\s]", " ", lowered)
        words = [w for w in cleaned.split() if w]
        acknowledgment_tokens = {
            "ok",
            "okay",
            "sure",
            "roger",
            "got",
            "it",
            "gotcha",
            "understood",
            "noted",
            "alright",
            "k",
        }
        if not words or len(words) > 4:
            return False
        if any(len(w) > 12 for w in words):
            return False
        if not all(w in acknowledgment_tokens for w in words):
            return False

        return True

    def _looks_like_knowledge_request(self, prompt: str) -> bool:
        if not prompt:
            return False
        lowered = prompt.lower()
        patterns = (
            r"\bsummarize\b",
            r"\bsummarise\b",
            r"\bexplain\b",
            r"\bwhat does\b",
            r"\bwhat is\b",
            r"\bwho is\b",
            r"\btell me about\b",
            r"\baccording to\b",
            r"\bin the book\b",
            r"\bin the paper\b",
            r"\bin the document\b",
            r"\bfrom the (?:docs|documentation|manual)\b",
        )
        return any(re.search(pattern, lowered) for pattern in patterns)

    def _rag_indices_exist(self) -> bool:
        if not self._ensure_rag_components() or not self.indexer:
            return False
        try:
            return bool(self.indexer.list_indices())
        except Exception:
            return False

    def _should_add_rag_hint(self) -> bool:
        if self._rag_retrieval_attempted:
            return False
        last_user_msg = self.conversation.get_last_user_message()
        if not last_user_msg or not self._looks_like_knowledge_request(last_user_msg.content):
            return False
        return self._rag_indices_exist()

    async def _confirm_tool_execution(self, tool: BaseTool, args: dict[str, Any]) -> bool:
        """Prompt the user to confirm a mutating tool run."""
        prompt_args = self._sanitize_arguments(args)
        display_warning(
            f"Tool '{tool.name}' (risk={getattr(tool, 'risk_level', 'unknown')}) requested with args: {prompt_args}"
        )
        response = (await get_user_input("Allow tool execution? [y/N]: ")).strip().lower()
        return response in {"y", "yes"}

    async def _run_tool(
        self,
        tool: BaseTool,
        call: ToolCall,
        tool_id: Any | None = None,
        *,
        allowed_paths: list[Path] | None = None,
        denied_paths: list[Path] | None = None,
    ) -> tuple[ToolResult, dict[str, Any]]:
        """Execute a tool through centralized policy and confirmation gates."""
        qualified_id = getattr(tool_id, "qualified", None) or getattr(tool, "qualified_id", None)
        audit: dict[str, Any] = {
            "tool_name": qualified_id or tool.name,
            "qualified_tool_id": qualified_id or tool.name,
            "input": self._sanitize_arguments(call.arguments),
            "risk_level": getattr(tool, "risk_level", "read"),
            "mutates_state": bool(getattr(tool, "mutates_state", False)),
            "provider_id": getattr(tool, "provider_id", ""),
            "provider_version": getattr(tool, "provider_version", ""),
            "server_id": getattr(tool, "server_id", ""),
            "transport_requires_network": getattr(tool, "transport_requires_network", False),
            "tool_requires_network": getattr(tool, "tool_requires_network", False),
        }

        # Check for malformed JSON arguments
        if "__raw_arguments" in call.arguments:
            msg = "Tool call arguments could not be parsed (malformed JSON)."
            result = ToolResult(
                success=False,
                content="",
                error=msg,
                metadata={"policy": "malformed_args", "duration_ms": 0},
            )
            audit.update(
                {
                    "decision": "malformed_args",
                    "output_sha256": None,
                    "output_size": 0,
                    "error": msg,
                    "raw_arguments": call.arguments.get("__raw_arguments"),
                }
            )
            return result, audit

        try:
            filtered_args = self._validate_tool_arguments(tool, call.arguments)
        except ValueError as exc:
            message = str(exc)
            result = ToolResult(
                success=False,
                content="",
                error=message,
                metadata={"policy": "invalid_args", "duration_ms": 0},
            )
            audit.update(
                {
                    "decision": "invalid_args",
                    "output_sha256": None,
                    "output_size": 0,
                    "error": message,
                }
            )
            return result, audit

        audit["input"] = self._sanitize_arguments(filtered_args)

        decision = self.tool_policy.evaluate(
            tool,
            filtered_args,
            workspace=self.workspace.current.root if self.workspace.current else None,
            allowed_paths=allowed_paths,
            denied_paths=denied_paths,
        )
        path_validation: dict[str, dict[str, Any]] = {}
        for param in getattr(tool, "path_params", ()):
            value = filtered_args.get(param)
            if not value:
                continue
            try:
                resolved = resolve_and_validate_path(
                    value,
                    workspace=self.workspace.current,
                    allowed_paths=allowed_paths or self.config.tools.allowed_paths,
                    denied_paths=denied_paths or self.config.tools.denied_paths,
                )
                path_validation[param] = {
                    "value": value,
                    "resolved": str(resolved),
                    "allowed": True,
                }
            except Exception as exc:
                path_validation[param] = {"value": value, "allowed": False, "error": str(exc)}
        allowlist = getattr(self.config.tools, "allowlist", None) or getattr(
            self.config.tools, "allowed_tools", None
        )
        denylist = getattr(self.config.tools, "denylist", None) or getattr(
            self.config.tools, "denied_tools", None
        )
        qualified_name = qualified_id or tool.name
        self.last_policy_trace = {
            "event": "policy_check",
            "recipe": None,
            "step": None,
            "tool_id": qualified_name,
            "risk": getattr(tool, "risk_level", "unknown"),
            "risk_level": getattr(tool, "risk_level", "unknown"),
            "mode": self.desktop_ops_mode,
            "approval_required": self.config.tools.confirmation_required
            and self._requires_confirmation(tool),
            "approval_result": decision.allowed,
            "approval_reason": decision.reason,
            "paths_validated": path_validation,
            "allowlist_match": bool(allowlist and qualified_name in allowlist),
            "denylist_match": bool(denylist and qualified_name in denylist),
            "start_time": None,
            "end_time": None,
        }
        audit["policy_reason"] = decision.reason
        audit["policy_allowed"] = decision.allowed
        audit["duration_ms"] = 0
        audit["success"] = False

        if not decision.allowed:
            result = ToolResult(
                success=False,
                content="",
                error=decision.reason,
                metadata={"policy": "denied", "duration_ms": 0},
            )
            audit.update(
                {
                    "decision": "policy_denied",
                    "output_sha256": None,
                    "output_size": 0,
                    "error": decision.reason,
                }
            )
            return result, audit

        if self.config.tools.confirmation_required and self._requires_confirmation(tool):
            confirmed = await self._confirm_tool_execution(tool, call.arguments)
            if not confirmed:
                result = ToolResult(
                    success=False,
                    content="",
                    error="Tool execution cancelled by user",
                    metadata={"policy": "cancelled", "duration_ms": 0},
                )
                audit.update(
                    {
                        "decision": "user_denied",
                        "output_sha256": None,
                        "output_size": 0,
                        "error": "Tool execution cancelled by user",
                    }
                )
                return result, audit

        exec_args = dict(filtered_args)
        exec_args.setdefault("workspace", self.workspace.current)
        exec_args.setdefault("allowed_paths", allowed_paths or self.config.tools.allowed_paths)
        exec_args.setdefault("denied_paths", denied_paths or self.config.tools.denied_paths)

        start = time.time()
        try:
            result = await tool.execute(**exec_args)
        except Exception as e:
            result = ToolResult(success=False, content="", error=str(e))
        duration = int((time.time() - start) * 1000)

        audit["duration_ms"] = duration
        result.metadata = {**(result.metadata or {}), "duration_ms": duration, "policy": decision.reason}
        audit.update(
            {
                "decision": "allowed",
                "success": result.success,
                "error": (result.error or "")[:200] if result.error else None,
            }
        )

        output = result.content if result.success else (result.error or "")
        output_hash, output_size = self._hash_output(output)
        audit["output_sha256"] = output_hash
        audit["output_size"] = output_size
        return result, audit
    
    async def start(self) -> int:
        """Start the main application loop.
        
        Returns:
            Exit code (0 for success).
        """
        display_welcome(self.config)
        
        # Verify Ollama connection
        if not await self.ollama.is_available():
            display_error(
                f"Cannot connect to Ollama at {self.config.ollama.host}\n"
                "Make sure Ollama is running: ollama serve"
            )
            return 1

        # C.6 - Run Recovery UX: Check for incomplete runs on startup
        await self._check_incomplete_runs()
        
        # Main loop
        while self.running:
            try:
                default_text = self.next_input_default
                self.next_input_default = ""
                user_input = await get_user_input(
                    status_callback=self._get_status_bar,
                    default=default_text
                )
                
                if not user_input.strip():
                    continue
                
                # Execute process_input as a cancellable task
                self.processing_task = asyncio.create_task(self.process_input(user_input))
                try:
                    await self.processing_task
                except asyncio.CancelledError:
                    # Task was cancelled, already handled in KeyboardInterrupt block or task logic
                    pass
                finally:
                    self.processing_task = None
                    self.last_action_status = "Idle"
                
            except KeyboardInterrupt:
                # Cancel active run if any
                if self.current_run and self.current_run.cancellation_token:
                    self.current_run.cancellation_token.cancel()
                    from aries.core.agent_run import RunStatus
                    if self.current_run.status in (RunStatus.RUNNING, RunStatus.PLANNING):
                        self.current_run.status = RunStatus.CANCELLED
                        if self.run_manager:
                            self.run_manager.save_run(self.current_run)
                        console.print("\n[yellow]Run cancelled.[/yellow]")
                
                if self.processing_task and not self.processing_task.done():
                    console.print("\n[yellow]Cancelling...[/yellow]")
                    self.processing_task.cancel()
                    try:
                        await self.processing_task
                    except asyncio.CancelledError:
                        pass
                    self.last_action_summary = "Cancelled"
                else:
                    console.print("\n[dim]Use /exit to quit[/dim]")
            except EOFError:
                break
            except AriesError as e:
                display_error(str(e))
            except Exception as e:
                display_error(f"Unexpected error: {e}")
        
        return 0

    
    async def process_input(self, user_input: str) -> None:
        """Process user input - either command or chat message.
        
        Args:
            user_input: Raw user input string.
        """
        user_input = user_input.strip()
        
        # Heuristic: "help /cmd" -> "/help cmd"
        if user_input.lower().startswith("help /"):
            user_input = "/" + user_input
            
        self.last_action_status = "Running"
        
        # Check if it's a command
        if is_command(user_input):
            await self.handle_command(user_input)
        else:
            await self.handle_chat(user_input)
    
    async def handle_command(self, input_str: str) -> None:
        """Handle a slash command.
        
        Args:
            input_str: Command string starting with '/'.
        """
        parts = input_str[1:].split(maxsplit=1)
        cmd_name = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""
        
        command = get_command(cmd_name)
        if command is None:
            display_error(f"Unknown command: /{cmd_name}\nType /help for available commands.")
            return
        
        try:
            await command.execute(self, args)
            self.last_action_summary = f"Command /{cmd_name} executed"
            self.last_action_details = {"command": cmd_name, "args": args, "timestamp": time.time()}
        except Exception as e:
            self.last_action_summary = f"Command /{cmd_name} failed"
            self.last_action_details = {"command": cmd_name, "args": args, "error": str(e), "timestamp": time.time()}
            raise e
    
    async def handle_chat(self, message: str) -> None:
        """Handle a chat message - send to LLM and display response.
        
        Args:
            message: User's chat message.
        """
        msg = self.conversation.add_user_message(message)
        self._log_transcript("user", message, msg_id=str(uuid.uuid4()))
        await self._run_assistant()
    
    async def _run_assistant(self) -> None:
        """Run chat loop with optional tool handling."""
        max_tool_iterations = 10
        iteration = 0
        self._rag_retrieval_attempted = False

        # Get the user's query for RAG retrieval
        last_user_msg = self.conversation.get_last_user_message()
        user_query = last_user_msg.content if last_user_msg else ""

        while iteration < max_tool_iterations:
            iteration += 1
            messages = self.conversation.get_messages_for_ollama()
            if self.current_rag and user_query:
                self._rag_retrieval_attempted = True
                context_chunks = await self._retrieve_context(user_query)
                if context_chunks:
                    context_text = "\n\n".join(
                        f"[{chunk.source}] {chunk.content}" for chunk in context_chunks
                    )
                    messages.insert(
                        1,
                        {
                            "role": "system",
                            "content": f"Context:\n{context_text}",
                        },
                    )
            response = await self.ollama.chat(
                model=self.current_model,
                messages=messages,
                tools=self.tool_definitions or None,
                raw=True,
            )
            message_payload = response.get("message", {}) if isinstance(response, dict) else {}
            tool_calls_raw = message_payload.get("tool_calls") or []

            if tool_calls_raw:
                tool_calls = self.conversation.parse_tool_calls(tool_calls_raw)
                self.conversation.add_assistant_message(
                    message_payload.get("content", ""),
                    tool_calls=tool_calls,
                )
                self._log_transcript(
                    "assistant",
                    message_payload.get("content", "") or "",
                    msg_id=str(uuid.uuid4()),
                    extra={"tool_calls": tool_calls_raw},
                )
                await self._execute_tool_calls(tool_calls)
                continue

            await self._stream_assistant_response(initial_response=message_payload.get("content"))
            break
        else:
            display_error("Maximum tool iterations reached. Stopping.")

    async def _retrieve_context(self, query: str):
        """Fetch RAG context if an index is active."""
        if not self._ensure_rag_components() or not self.retriever:
            self._warn_once("rag:missing", self.rag_dependency_message())
            return []

        try:
            chunks = await self.retriever.retrieve(query)
            handles = self.retriever.last_handles
            self._log_transcript(
                "system",
                f"Retrieved {len(chunks)} chunks",
                msg_id=str(uuid.uuid4()),
                extra={
                    "tool_name": "rag_retrieve",
                    "status": "success",
                    "query": query,
                    "index": self.retriever.current_index,
                    "returned_handles": handles,
                    "top_k": self.retriever.config.top_k,
                },
            )
            return chunks
        except Exception as exc:
            display_error(f"RAG retrieval failed: {exc}")
            self._log_transcript(
                "system",
                "RAG retrieval failed",
                msg_id=str(uuid.uuid4()),
                extra={
                    "tool_name": "rag_retrieve",
                    "status": "fail",
                    "error": str(exc),
                    "query": query,
                },
            )
            return []
    
    async def _execute_tool_calls(self, tool_calls: Iterable[ToolCall]) -> None:
        """Execute tool calls requested by the assistant."""
        max_display_chars = 2000

        for call in tool_calls:
            # Guard: Malformed JSON or Parse Error
            if "__raw_arguments" in call.arguments:
                msg = "Tool call was received but could not be executed due to invalid or empty arguments."
                display_warning(msg)
                self.conversation.add_tool_result_message(
                    tool_call_id=call.id or call.name,
                    content=msg,
                    success=False,
                    error=TOOL_CALL_PARSE_ERROR,
                    tool_name=call.name,
                )
                self._log_transcript(
                    "tool",
                    msg,
                    msg_id=str(uuid.uuid4()),
                    extra={
                        "tool_name": call.name,
                        "status": "fail",
                        "error": TOOL_CALL_PARSE_ERROR,
                        "raw_arguments": call.arguments.get("__raw_arguments"),
                    },
                )
                continue

            tool_id, tool, error = self._resolve_tool_reference(call.name)
            tool_label = getattr(tool_id, "qualified", None) or call.name

            # Guard: Missing Tool Name (if parse passed but name missing)
            if not call.name:
                msg = "Tool call was received but could not be executed (missing tool name)."
                display_warning(msg)
                self.conversation.add_tool_result_message(
                    tool_call_id=call.id,
                    content=msg,
                    success=False,
                    error=TOOL_CALL_PARSE_ERROR,
                )
                continue

            if error or tool is None:
                display_error(error or f"Unknown tool requested: {call.name}")
                self.conversation.add_tool_result_message(
                    tool_call_id=call.id or call.name,
                    content=error or f"Unknown tool: {call.name}",
                    success=False,
                    error=error or "Unknown tool",
                    tool_name=tool_label,
                )
                continue

            # Guard: Empty Arguments when Required
            schema = getattr(tool, "parameters", {})
            required_params = schema.get("required", []) if isinstance(schema, dict) else []
            if not call.arguments and required_params:
                msg = "Tool call was received but could not be executed due to invalid or empty arguments."
                display_warning(msg)
                self.conversation.add_tool_result_message(
                    tool_call_id=call.id or call.name,
                    content=msg,
                    success=False,
                    error=TOOL_CALL_INVALID_ARGUMENTS,
                    tool_name=tool_label,
                )
                self._log_transcript(
                    "tool",
                    msg,
                    msg_id=str(uuid.uuid4()),
                    extra={
                        "tool_name": tool_label,
                        "status": "fail",
                        "error": TOOL_CALL_INVALID_ARGUMENTS,
                    },
                )
                continue

            result, audit = await self._run_tool(tool, call, tool_id)
            result.metadata = result.metadata or {}

            output = result.content if result.success else (result.error or "")
            bounded_output, truncated = self._truncate_output(output, limit=max_display_chars)
            self.conversation.add_tool_result_message(
                tool_call_id=call.id or call.name,
                content=bounded_output,
                success=result.success,
                error=result.error,
                tool_name=tool_label,
            )
            self._log_transcript(
                "tool",
                bounded_output,
                msg_id=str(uuid.uuid4()),
                extra={
                    "tool_name": tool_label,
                    "provider_id": getattr(tool, "provider_id", ""),
                    "provider_version": getattr(tool, "provider_version", ""),
                    "server_id": getattr(tool, "server_id", ""),
                    "qualified_tool_id": getattr(tool, "qualified_id", tool_label),
                    "status": "success" if result.success else "fail",
                    "duration_ms": audit.get("duration_ms"),
                    "input": audit.get("input"),
                    "policy_reason": audit.get("policy_reason"),
                    "policy_allowed": audit.get("policy_allowed"),
                    "decision": audit.get("decision"),
                    "output_size": audit.get("output_size"),
                    "output_sha256": audit.get("output_sha256"),
                    "truncated": truncated,
                    "error": audit.get("error"),
                    "transport_requires_network": audit.get("transport_requires_network"),
                    "tool_requires_network": audit.get("tool_requires_network"),
                },
            )
            self._maybe_register_artifact(result, tool)
            
            # Phase A: Summary and State Update
            duration_s = (audit.get("duration_ms", 0) or 0) / 1000.0
            artifact_count = len(result.artifacts) if result.artifacts else 0
            # Also count artifacts in metadata if not in direct list (legacy)
            if not result.artifacts and result.metadata and result.metadata.get("artifact"):
                 # Simple heuristic, full counting is in _maybe_register_artifact but we want a quick number
                 artifact_count = 1
            
            status_str = "Done" if result.success else "Failed"
            summary = f"{status_str}: {tool_label} → {artifact_count} artifacts, {duration_s:.2f}s"
            
            self.last_action_summary = summary
            self.last_action_status = "Idle"
            self.last_action_details = {
                "tool": tool_label,
                "status": "success" if result.success else "error",
                "duration_ms": audit.get("duration_ms"),
                "artifacts": artifact_count,
                "input": audit.get("input"),
                "error": result.error,
                "timestamp": time.time()
            }

            if result.success:
                console.print(f"[green]✓ {summary}[/green]")
            else:
                error_detail = result.error or "Unknown error"
                display_error(f"{summary}\nReason: {error_detail}")
            
            if output and result.success:
                display_output = output[:max_display_chars]
                if len(output) > max_display_chars:
                    display_output += f"\n... (truncated, {len(output)} total chars)"
                console.print(f"\n[dim]{tool_label} output:[/dim]\n{display_output}\n")
    
    async def _stream_assistant_response(self, initial_response: str | None = None) -> None:
        """Stream the assistant's final response and record it."""
        messages = self.conversation.get_messages_for_ollama()
        
        response_text = ""
        classification = None
        if self.config.ui.stream_output:
            started = False
            async for chunk in self.ollama.chat_stream(
                model=self.current_model,
                messages=messages,
                tools=self.tool_definitions or None,
            ):
                response_text += chunk
                if not started and chunk.strip() == "":
                    continue

                if not started:
                    started = True
                    console.print()

                console.print(chunk, end="")
            
            if started:
                console.print("\n")
        else:
            if initial_response is not None:
                response_text = initial_response
            else:
                response_text = await self.ollama.chat(
                    model=self.current_model,
                    messages=messages,
                )
            
            if response_text.strip():
                console.print(f"\n{response_text}\n")
        
        stripped = response_text.strip()
        if not stripped:
            classification = EMPTY_ASSISTANT_RESPONSE
            rag_hint = ""
            if self._should_add_rag_hint():
                rag_hint = (
                    " Tip: Select an index with `/rag use <id>` and re-ask, or verify "
                    "retrieval with `/rag last`."
                )
            display_warning(
                "(Model returned an empty response — try rephrasing or switching models. "
                f"Use /last for details.){rag_hint}"
            )
        elif self._is_non_actionable_response(response_text, tool_calls_present=False):
            # Guard against acknowledgement-only replies that provide no actionable detail
            display_warning(
                "Model response contained no actionable content. "
                "(Assistant responded with an acknowledgement-only message; provide more detail or request a specific action.)"
            )

        if classification == EMPTY_ASSISTANT_RESPONSE:
            now = time.time()
            self.last_model_turn = {
                "timestamp": now,
                "model": self.current_model,
                "raw_response_length": len(response_text),
                "stripped_response_length": len(stripped),
                "tool_calls_count": 0,
                "classification": classification,
            }
        elif self.last_model_turn and (self.last_model_turn.get("classification") == EMPTY_ASSISTANT_RESPONSE):
            # Clear stale empty-response record once a normal response arrives
            self.last_model_turn = None

        self.conversation.add_assistant_message(response_text)
        
        extra = {}
        if classification:
            extra["classification"] = classification
            
        self._log_transcript("assistant", response_text, msg_id=str(uuid.uuid4()), extra=extra)
    
    def stop(self) -> None:
        """Stop the application loop."""
        self.running = False

    def _log_transcript(self, role: str, content: str, msg_id: str, extra: dict | None = None) -> None:
        if not self.workspace.logger:
            return
        entry = TranscriptEntry(
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            role=role,
            content=content,
            conversation_id=self.conversation_id,
            message_id=msg_id,
            extra=extra or {},
        )
        self.workspace.logger.log(entry)

    def _maybe_register_artifact(self, result: ToolResult, tool: BaseTool) -> None:
        registry = self.workspace.artifacts
        if not registry or not getattr(tool, "emits_artifacts", False):
            return

        metadata = result.metadata or {}
        artifact_meta = metadata.get("artifact")
        hints: list[ArtifactRef] = []
        if isinstance(artifact_meta, list):
            hints.extend([ref for ref in (ArtifactRef.from_hint(h) for h in artifact_meta) if ref])
        else:
            ref = ArtifactRef.from_hint(artifact_meta)
            if ref:
                hints.append(ref)

        if result.artifacts:
            hints.extend([ref for ref in (ArtifactRef.from_hint(h) for h in result.artifacts) if ref])

        legacy_path = metadata.get("path")
        if legacy_path:
            legacy_ref = ArtifactRef.from_hint({"path": legacy_path})
            if legacy_ref:
                hints.append(legacy_ref)

        if not hints:
            return

        seen_paths: set[str] = set()
        for ref in hints:
            try:
                path = self.workspace.resolve_path(ref.path)
            except FileToolError as exc:
                logger.warning("Artifact outside allowed paths ignored: %s", exc)
                continue

            normalized = str(path)
            if normalized in seen_paths:
                continue
            seen_paths.add(normalized)

            if not path.exists():
                logger.warning("Artifact path not found for registration: %s", path)
                continue

            extra = dict(ref.extra)
            description = ref.description
            source = ref.source or tool.name
            if ref.name:
                extra.setdefault("name", ref.name)
            if ref.mime:
                extra.setdefault("mime", ref.mime)
            if ref.type:
                extra.setdefault("type", ref.type)
            if ref.size_bytes is not None:
                extra.setdefault("size_bytes", ref.size_bytes)
            if ref.hash:
                extra.setdefault("hash", ref.hash)

            registry.register_file(path, description=description, source=source, extra=extra)

    def _apply_workspace_index_path(self) -> None:
        if self.workspace.current and self.indexer and self.retriever:
            index_dir = self.workspace.current.index_dir
            self.indexer.config.indices_dir = index_dir
            self.retriever.config.indices_dir = index_dir


async def run_cli() -> int:
    """Run the Aries CLI application.
    
    Returns:
        Exit code (0 for success).
    """
    # Load configuration
    config_path = Path("config.yaml")
    config = load_config(config_path if config_path.exists() else None)
    
    # Create and start application
    try:
        app = Aries(config)
    except AriesError as exc:
        display_error(str(exc))
        return 1
    return await app.start()


def main() -> None:
    """Console script entrypoint for Aries."""
    exit_code = asyncio.run(run_cli())
    if exit_code:
        raise SystemExit(exit_code)
