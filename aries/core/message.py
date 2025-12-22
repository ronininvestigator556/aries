"""
Message data structures for conversation management.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class Role(str, Enum):
    """Message roles in a conversation."""
    
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass
class ToolCall:
    """Represents a tool invocation request from the LLM."""
    
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class ToolResult:
    """Represents the result of a tool execution."""
    
    tool_call_id: str
    content: str
    success: bool = True
    error: str | None = None


@dataclass
class Message:
    """A single message in a conversation."""
    
    role: Role
    content: str
    timestamp: datetime = field(default_factory=datetime.now)
    tool_calls: list[ToolCall] | None = None
    tool_results: list[ToolResult] | None = None
    images: list[str] | None = None  # Base64-encoded images for vision models
    
    def to_ollama_format(self) -> dict[str, Any]:
        """Convert message to Ollama API format.
        
        Returns:
            Dictionary suitable for Ollama chat API.
        """
        msg: dict[str, Any] = {
            "role": self.role.value,
            "content": self.content,
        }
        
        if self.images:
            msg["images"] = self.images
        
        return msg
    
    @classmethod
    def user(cls, content: str, images: list[str] | None = None) -> "Message":
        """Create a user message.
        
        Args:
            content: Message content.
            images: Optional list of base64-encoded images.
            
        Returns:
            New Message instance.
        """
        return cls(role=Role.USER, content=content, images=images)
    
    @classmethod
    def assistant(cls, content: str) -> "Message":
        """Create an assistant message.
        
        Args:
            content: Message content.
            
        Returns:
            New Message instance.
        """
        return cls(role=Role.ASSISTANT, content=content)
    
    @classmethod
    def system(cls, content: str) -> "Message":
        """Create a system message.
        
        Args:
            content: System prompt content.
            
        Returns:
            New Message instance.
        """
        return cls(role=Role.SYSTEM, content=content)
