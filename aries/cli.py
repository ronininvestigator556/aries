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

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from aries.config import Config, load_config
from aries.exceptions import AriesError, CommandError
from aries.ui.display import display_error, display_welcome, display_response
from aries.ui.input import get_user_input
from aries.commands import get_command, is_command
from aries.core.conversation import Conversation
from aries.core.ollama_client import OllamaClient


console = Console()


class Aries:
    """Main Aries application class."""
    
    def __init__(self, config: Config) -> None:
        """Initialize Aries.
        
        Args:
            config: Application configuration.
        """
        self.config = config
        self.conversation = Conversation()
        self.ollama = OllamaClient(config.ollama)
        self.running = True
        self.current_model: str = config.ollama.default_model
        self.current_rag: str | None = None
        self.current_prompt: str = config.prompts.default
    
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
        # Add user message to conversation
        self.conversation.add_user_message(message)
        
        # Get context from RAG if active
        rag_context = ""
        if self.current_rag:
            # TODO: Implement RAG retrieval
            pass
        
        # Build messages for Ollama
        messages = self.conversation.get_messages_for_ollama()
        
        # Stream response
        console.print()
        response_text = ""
        
        async for chunk in self.ollama.chat_stream(
            model=self.current_model,
            messages=messages,
        ):
            console.print(chunk, end="")
            response_text += chunk
        
        console.print("\n")
        
        # Add assistant response to conversation
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
