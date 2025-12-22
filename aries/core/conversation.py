"""
Conversation management for message history and context.
"""

from __future__ import annotations

import json
from typing import Any

import tiktoken

from aries.core.message import Message, Role, ToolCall, ToolResultMessage


class Conversation:
    """Manages conversation history, context windows, and tool tracking."""
    
    def __init__(
        self,
        system_prompt: str | None = None,
        max_context_tokens: int = 4096,
        max_messages: int = 100,
        encoding: str = "cl100k_base",
    ) -> None:
        """Initialize conversation.
        
        Args:
            system_prompt: Optional system prompt to start with.
            max_context_tokens: Maximum tokens to retain in history.
            max_messages: Maximum number of messages to keep.
            encoding: Token encoding name for estimation.
        """
        self.messages: list[Message] = []
        self.system_prompt = system_prompt
        self.max_context_tokens = max_context_tokens
        self.max_messages = max_messages
        self.encoding = encoding
        try:
            self._encoder = tiktoken.get_encoding(encoding)
        except Exception:
            self._encoder = tiktoken.get_encoding("cl100k_base")
            self.encoding = "cl100k_base"
    
    def add_message(self, message: Message) -> None:
        """Add a message to the conversation.
        
        Args:
            message: Message to add.
        """
        self.messages.append(message)
        self._prune_history()
    
    def add_user_message(self, content: str, images: list[str] | None = None) -> Message:
        """Add a user message.
        
        Args:
            content: Message content.
            images: Optional base64-encoded images.
            
        Returns:
            The created message.
        """
        msg = Message.user(content, images)
        self.add_message(msg)
        return msg
    
    def add_assistant_message(
        self,
        content: str,
        tool_calls: list[ToolCall] | None = None,
    ) -> Message:
        """Add an assistant message.
        
        Args:
            content: Message content.
            tool_calls: Optional tool call requests from the assistant.
            
        Returns:
            The created message.
        """
        msg = Message.assistant(content, tool_calls=tool_calls)
        self.add_message(msg)
        return msg
    
    def add_tool_result_message(
        self,
        tool_call_id: str,
        content: str,
        success: bool = True,
        error: str | None = None,
    ) -> Message:
        """Add a tool result message.

        Args:
            tool_call_id: Identifier of the originating tool call.
            content: Tool output content.
            success: Whether the tool execution succeeded.
            error: Optional error message.

        Returns:
            The created message.
        """
        result = ToolResultMessage(
            tool_call_id=tool_call_id,
            content=content,
            success=success,
            error=error,
        )
        message = Message(
            role=Role.TOOL,
            content=content,
            tool_call_id=tool_call_id,
            tool_results=[result],
        )
        self.add_message(message)
        return message
    
    def set_system_prompt(self, prompt: str) -> None:
        """Set the system prompt.
        
        Args:
            prompt: System prompt content.
        """
        self.system_prompt = prompt
    
    def clear(self) -> None:
        """Clear all messages (keeps system prompt)."""
        self.messages.clear()
    
    def get_messages_for_ollama(self) -> list[dict[str, Any]]:
        """Get messages formatted for Ollama API.
        
        Returns:
            List of message dictionaries for Ollama.
        """
        self._prune_history()
        result: list[dict[str, Any]] = []
        
        if self.system_prompt:
            result.append({
                "role": "system",
                "content": self.system_prompt,
            })
        
        for msg in self.messages:
            result.append(msg.to_ollama_format())
        
        return result
    
    def get_last_user_message(self) -> Message | None:
        """Get the last user message.
        
        Returns:
            Last user message or None.
        """
        for msg in reversed(self.messages):
            if msg.role == Role.USER:
                return msg
        return None
    
    def get_last_assistant_message(self) -> Message | None:
        """Get the last assistant message.
        
        Returns:
            Last assistant message or None.
        """
        for msg in reversed(self.messages):
            if msg.role == Role.ASSISTANT:
                return msg
        return None
    
    def parse_tool_calls(self, tool_calls: list[dict[str, Any]]) -> list[ToolCall]:
        """Convert Ollama tool call payloads to ToolCall objects.
        
        Args:
            tool_calls: Raw tool call payloads from Ollama.
            
        Returns:
            Parsed ToolCall objects.
        """
        parsed: list[ToolCall] = []
        for call in tool_calls:
            function = call.get("function", {})
            arguments = function.get("arguments", {})
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except json.JSONDecodeError:
                    arguments = {"__raw_arguments": arguments}
            parsed.append(
                ToolCall(
                    id=call.get("id", ""),
                    name=function.get("name", ""),
                    arguments=arguments if isinstance(arguments, dict) else {},
                )
            )
        return parsed
    
    @property
    def message_count(self) -> int:
        """Get total message count."""
        return len(self.messages)
    
    @property
    def total_tokens(self) -> int:
        """Estimate total tokens in the retained conversation."""
        return self._estimate_total_tokens()
    
    def __len__(self) -> int:
        """Return message count."""
        return len(self.messages)
    
    def _estimate_total_tokens(self) -> int:
        """Estimate tokens for current history plus system prompt."""
        total = 0
        if self.system_prompt:
            total += self._estimate_tokens(self.system_prompt)
        
        for message in self.messages:
            total += self._estimate_message_tokens(message)
        return total
    
    def _estimate_message_tokens(self, message: Message) -> int:
        """Estimate token usage for a message."""
        tokens = self._estimate_tokens(message.content)
        
        if message.tool_calls:
            for tool_call in message.tool_calls:
                tokens += self._estimate_tokens(tool_call.name)
                tokens += self._estimate_tokens(json.dumps(tool_call.arguments))
        
        if message.tool_results:
            for result in message.tool_results:
                tokens += self._estimate_tokens(result.content)
                if result.error:
                    tokens += self._estimate_tokens(result.error)
        
        return tokens
    
    def _estimate_tokens(self, text: str) -> int:
        """Estimate tokens for a string using the configured encoding."""
        return len(self._encoder.encode(text or ""))
    
    def _prune_history(self) -> None:
        """Prune history based on message count and token limits."""
        while len(self.messages) > self.max_messages:
            if not self._remove_oldest_message():
                break
        
        while self._estimate_total_tokens() > self.max_context_tokens:
            if not self._remove_oldest_message():
                break
    
    def _remove_oldest_message(self) -> bool:
        """Remove the oldest non-system message.
        
        Returns:
            True if a message was removed.
        """
        for idx, message in enumerate(self.messages):
            if message.role != Role.SYSTEM:
                self.messages.pop(idx)
                return True
        return False
