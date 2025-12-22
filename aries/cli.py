"""
Main CLI loop and command routing for Aries.

This module handles:
- User input processing
- Command parsing and routing
- Chat message handling
- Main application loop
"""

import asyncio
import hashlib
import logging
import time
import uuid
from pathlib import Path
from typing import Any, Iterable

from rich.console import Console

from aries.commands import get_command, is_command
from aries.config import Config, load_config
from aries.core.conversation import Conversation
from aries.core.message import ToolCall
from aries.core.ollama_client import OllamaClient
from aries.core.tool_policy import ToolPolicy
from aries.core.tool_registry import ToolRegistry
from aries.core.profile import Profile, ProfileManager
from aries.core.workspace import ArtifactRef, TranscriptEntry, WorkspaceManager
from aries.exceptions import FileToolError
from aries.core.tokenizer import TokenEstimator
from aries.exceptions import AriesError, ConfigError
from aries.rag.indexer import Indexer
from aries.rag.retriever import Retriever
from aries.providers import CoreProvider
from aries.tools.base import BaseTool, ToolResult
from aries.ui.display import display_error, display_info, display_warning, display_welcome
from aries.ui.input import get_user_input


console = Console()
logger = logging.getLogger(__name__)


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
        self.tool_registry.register_provider(CoreProvider())
        self.tools: list[BaseTool] = self.tool_registry.list_tools()
        self.tool_definitions = [tool.to_ollama_format() for tool in self.tools]
        self.tool_map: dict[str, BaseTool] = self.tool_registry.tools
        self._token_estimator = TokenEstimator(
            mode=config.tokens.mode,
            encoding=config.tokens.encoding,
            approx_chars_per_token=config.tokens.approx_chars_per_token,
        )
        self.profiles = ProfileManager(config.profiles.directory)
        self.tool_policy = ToolPolicy(config.tools)
        self.workspace = WorkspaceManager(config.workspace, config.tools)
        self.ollama = OllamaClient(config.ollama)
        self.indexer = Indexer(config.rag, self.ollama, token_estimator=self._token_estimator)
        self.retriever = Retriever(config.rag, self.ollama)
        self.running = True
        self.current_model: str = config.ollama.default_model
        self.current_rag: str | None = None
        self.conversation_id = str(uuid.uuid4())

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

    def _warn_once(self, key: str, message: str) -> None:
        """Emit a warning message once per key."""
        if key in self._warnings_shown:
            return
        display_warning(message)
        self._warnings_shown.add(key)

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

    def _requires_confirmation(self, tool: BaseTool) -> bool:
        """Determine whether a tool should require confirmation."""
        risk = getattr(tool, "risk_level", "read")
        if getattr(tool, "mutates_state", False):
            return True
        return risk in {"write", "exec"}

    def _sanitize_arguments(self, args: dict[str, Any]) -> dict[str, Any]:
        """Sanitize tool arguments for logging."""
        sanitized: dict[str, Any] = {}
        for key, value in args.items():
            if isinstance(value, str):
                sanitized[key] = value if len(value) <= 200 else value[:200] + "...[truncated]"
            else:
                sanitized[key] = value
        return sanitized

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

    async def _confirm_tool_execution(self, tool: BaseTool, args: dict[str, Any]) -> bool:
        """Prompt the user to confirm a mutating tool run."""
        prompt_args = self._sanitize_arguments(args)
        display_warning(
            f"Tool '{tool.name}' (risk={getattr(tool, 'risk_level', 'unknown')}) requested with args: {prompt_args}"
        )
        response = (await get_user_input("Allow tool execution? [y/N]: ")).strip().lower()
        return response in {"y", "yes"}

    async def _run_tool(self, tool: BaseTool, call: ToolCall) -> tuple[ToolResult, dict[str, Any]]:
        """Execute a tool through centralized policy and confirmation gates."""
        audit = {
            "tool_name": tool.name,
            "input": self._sanitize_arguments(call.arguments),
            "risk_level": getattr(tool, "risk_level", "read"),
            "mutates_state": bool(getattr(tool, "mutates_state", False)),
            "provider_id": getattr(tool, "provider_id", ""),
            "provider_version": getattr(tool, "provider_version", ""),
        }

        decision = self.tool_policy.evaluate(tool, call.arguments, workspace=self.workspace.current.root if self.workspace.current else None)
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

        exec_args = dict(call.arguments)
        exec_args.setdefault("workspace", self.workspace.current)
        exec_args.setdefault("allowed_paths", self.config.tools.allowed_paths)
        exec_args.setdefault("denied_paths", self.config.tools.denied_paths)

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
        
        # Main loop
        while self.running:
            try:
                user_input = await get_user_input()
                
                if not user_input.strip():
                    continue
                
                await self.process_input(user_input)
                
            except KeyboardInterrupt:
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
        
        await command.execute(self, args)
    
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

        # Get the user's query for RAG retrieval
        last_user_msg = self.conversation.get_last_user_message()
        user_query = last_user_msg.content if last_user_msg else ""

        while iteration < max_tool_iterations:
            iteration += 1
            messages = self.conversation.get_messages_for_ollama()
            if self.current_rag and user_query:
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
            tool = self.tool_map.get(call.name)
            if tool is None:
                display_error(f"Unknown tool requested: {call.name}")
                self.conversation.add_tool_result_message(
                    tool_call_id=call.id or call.name,
                    content=f"Unknown tool: {call.name}",
                    success=False,
                    error="Unknown tool",
                    tool_name=call.name,
                )
                continue
            result, audit = await self._run_tool(tool, call)
            result.metadata = result.metadata or {}

            output = result.content if result.success else (result.error or "")
            bounded_output, truncated = self._truncate_output(output, limit=max_display_chars)
            self.conversation.add_tool_result_message(
                tool_call_id=call.id or call.name,
                content=bounded_output,
                success=result.success,
                error=result.error,
                tool_name=call.name,
            )
            self._log_transcript(
                "tool",
                bounded_output,
                msg_id=str(uuid.uuid4()),
                extra={
                    "tool_name": call.name,
                    "provider_id": getattr(tool, "provider_id", ""),
                    "provider_version": getattr(tool, "provider_version", ""),
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
                },
            )
            self._maybe_register_artifact(result, tool)
            
            if result.success:
                display_info(f"Tool {call.name} executed")
            else:
                display_error(f"Tool {call.name} failed: {result.error}")
            
            if output:
                display_output = output[:max_display_chars]
                if len(output) > max_display_chars:
                    display_output += f"\n... (truncated, {len(output)} total chars)"
                console.print(f"\n[dim]{call.name} output:[/dim]\n{display_output}\n")
    
    async def _stream_assistant_response(self, initial_response: str | None = None) -> None:
        """Stream the assistant's final response and record it."""
        messages = self.conversation.get_messages_for_ollama()
        
        if self.config.ui.stream_output:
            console.print()
            response_text = ""
            
            async for chunk in self.ollama.chat_stream(
                model=self.current_model,
                messages=messages,
                tools=self.tool_definitions or None,
            ):
                console.print(chunk, end="")
                response_text += chunk
            
            console.print("\n")
        else:
            if initial_response is not None:
                response_text = initial_response
            else:
                response_text = await self.ollama.chat(
                    model=self.current_model,
                    messages=messages,
                )
            console.print(f"\n{response_text}\n")
        
        self.conversation.add_assistant_message(response_text)
        self._log_transcript("assistant", response_text, msg_id=str(uuid.uuid4()))
    
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
        if self.workspace.current:
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
