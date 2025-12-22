"""
Conversation management for message history and context.
"""

from typing import Any

from aries.core.message import Message, Role


class Conversation:
    """Manages conversation history and context."""
    
    def __init__(self, system_prompt: str | None = None) -> None:
        """Initialize conversation.
        
        Args:
            system_prompt: Optional system prompt to start with.
        """
        self.messages: list[Message] = []
        self.system_prompt = system_prompt
    
    def add_message(self, message: Message) -> None:
        """Add a message to the conversation.
        
        Args:
            message: Message to add.
        """
        self.messages.append(message)
    
    def add_user_message(self, content: str, images: list[str] | None = None) -> Message:
        """Add a user message.
        
        Args:
            content: Message content.
            images: Optional base64-encoded images.
            
        Returns:
            The created message.
        """
        msg = Message.user(content, images)
        self.messages.append(msg)
        return msg
    
    def add_assistant_message(self, content: str) -> Message:
        """Add an assistant message.
        
        Args:
            content: Message content.
            
        Returns:
            The created message.
        """
        msg = Message.assistant(content)
        self.messages.append(msg)
        return msg
    
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
        result: list[dict[str, Any]] = []
        
        # Add system prompt if set
        if self.system_prompt:
            result.append({
                "role": "system",
                "content": self.system_prompt,
            })
        
        # Add conversation messages
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
    
    @property
    def message_count(self) -> int:
        """Get total message count."""
        return len(self.messages)
    
    def __len__(self) -> int:
        """Return message count."""
        return len(self.messages)
