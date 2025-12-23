"""
Base tool class for Aries tools.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Literal


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
    provider_id: str = ""
    provider_version: str = ""
    mutates_state: bool = False
    emits_artifacts: bool = False
    risk_level: Literal["read", "write", "exec"] = "read"
    transport_requires_network: bool = False
    tool_requires_network: bool = False
    requires_shell: bool = False
    path_params: tuple[str, ...] = ()
    path_params_optional: bool = False
    uses_filesystem_paths: bool = False
    
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
    
    @property
    def requires_network(self) -> bool:
        """Effective network requirement including transport + tool intent."""
        return bool(self.transport_requires_network or self.tool_requires_network)

    def to_ollama_format(self, *, name: str | None = None) -> dict[str, Any]:
        """Convert tool to Ollama tool format.
        
        Returns:
            Dictionary suitable for Ollama tools parameter.
        """
        tool_name = name or self.name
        return {
            "type": "function",
            "function": {
                "name": tool_name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }
