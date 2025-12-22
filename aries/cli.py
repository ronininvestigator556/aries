"""
Main CLI loop and command routing for Aries.

This module handles:
- User input processing
- Command parsing and routing
- Chat message handling
- Main application loop
"""

import asyncio
from pathlib import Path
from typing import Iterable

from rich.console import Console

from aries.commands import get_command, is_command
from aries.config import Config, load_config
from aries.core.conversation import Conversation
from aries.core.message import ToolCall
from aries.core.ollama_client import OllamaClient
from aries.exceptions import AriesError
from aries.rag.indexer import Indexer
from aries.rag.retriever import Retriever
from aries.tools import get_all_tools
from aries.tools.base import BaseTool, ToolResult
from aries.ui.display import display_error, display_info, display_welcome
from aries.ui.input import get_user_input


console = Console()


class Aries:
    """Main Aries application class."""
    
    def __init__(self, config: Config) -> None:
        """Initialize Aries.
        
        Args:
            config: Application configuration.
        """
        self.config = config
        self.conversation = Conversation(
            system_prompt=self._load_system_prompt(),
            max_context_tokens=config.conversation.max_context_tokens,
            max_messages=config.conversation.max_messages,
            encoding=config.conversation.encoding,
        )
        self.ollama = OllamaClient(config.ollama)
        self.running = True
        self.current_model: str = config.ollama.default_model
        self.current_rag: str | None = None
        self.current_prompt: str = config.prompts.default
        self.tools: list[BaseTool] = get_all_tools()
        self.tool_definitions = [tool.to_ollama_format() for tool in self.tools]
        self.tool_map: dict[str, BaseTool] = {tool.name: tool for tool in self.tools}
        self.indexer = Indexer(config.rag, self.ollama)
        self.retriever = Retriever(config.rag, self.ollama)

    def _load_system_prompt(self) -> str | None:
        """Load the configured default system prompt if available."""
        prompt_path = Path(self.config.prompts.directory) / f"{self.config.prompts.default}.md"
        if not prompt_path.exists():
            return None
        
        try:
            return prompt_path.read_text(encoding="utf-8")
        except Exception:
            display_error(f"Failed to load system prompt from {prompt_path}")
            return None
    
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
        self.conversation.add_user_message(message)
        await self._run_assistant()
    
    async def _run_assistant(self) -> None:
        """Run chat loop with optional tool handling."""
        max_tool_iterations = 10
        iteration = 0

        while iteration < max_tool_iterations:
            iteration += 1
            messages = self.conversation.get_messages_for_ollama()
            if self.current_rag:
                context_chunks = await self._retrieve_context(message)
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
                await self._execute_tool_calls(tool_calls)
                continue

            await self._stream_assistant_response(initial_response=message_payload.get("content"))
            break
        else:
            display_error("Maximum tool iterations reached. Stopping.")

    async def _retrieve_context(self, query: str):
        """Fetch RAG context if an index is active."""
        try:
            return await self.retriever.retrieve(query)
        except Exception as exc:
            display_error(f"RAG retrieval failed: {exc}")
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
            
            try:
                result = await tool.execute(**call.arguments)
            except Exception as e:
                result = ToolResult(success=False, content="", error=str(e))
            
            output = result.content if result.success else (result.error or "")
            self.conversation.add_tool_result_message(
                tool_call_id=call.id or call.name,
                content=output,
                success=result.success,
                error=result.error,
                tool_name=call.name,
            )
            
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
    
    def stop(self) -> None:
        """Stop the application loop."""
        self.running = False


async def run_cli() -> int:
    """Run the Aries CLI application.
    
    Returns:
        Exit code (0 for success).
    """
    # Load configuration
    config_path = Path("config.yaml")
    config = load_config(config_path if config_path.exists() else None)
    
    # Create and start application
    app = Aries(config)
    return await app.start()
