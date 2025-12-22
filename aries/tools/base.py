"""
Base tool class for Aries tools.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class ToolResult:
    """Result of a tool execution."""
    
    success: bool
    content: str
    error: str | None = None
    metadata: dict[str, Any] | None = None
    artifacts: list[dict[str, Any]] | None = None


class BaseTool(ABC):
    """Abstract base class for tools."""
    
    name: str = ""
    description: str = ""
    mutates_state: bool = False
    emits_artifacts: bool = False
    risk_level: str = "read"
    
    @property
    @abstractmethod
    def parameters(self) -> dict[str, Any]:
        """JSON Schema for tool parameters.
        
        Returns:
            JSON Schema dictionary.
        """
        pass
    
    @abstractmethod
    async def execute(self, **kwargs: Any) -> ToolResult:
        """Execute the tool.
        
        Args:
            **kwargs: Tool-specific parameters.
            
        Returns:
            ToolResult with success/failure and content.
        """
        pass
    
    def to_ollama_format(self) -> dict[str, Any]:
        """Convert tool to Ollama tool format.
        
        Returns:
            Dictionary suitable for Ollama tools parameter.
        """
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }
