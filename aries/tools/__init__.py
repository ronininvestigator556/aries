"""
Tool system for Aries.

Tools are capabilities the LLM can invoke during a conversation,
such as reading files, searching the web, or executing shell commands.
"""

from aries.tools.base import BaseTool, ToolResult
from aries.tools.filesystem import ReadFileTool, WriteFileTool, ListDirectoryTool
from aries.tools.image import ReadImageTool
from aries.tools.shell import ExecuteShellTool
from aries.tools.web_search import WebSearchTool

# Tool registry
TOOLS: dict[str, type[BaseTool]] = {
    "read_file": ReadFileTool,
    "write_file": WriteFileTool,
    "list_directory": ListDirectoryTool,
    "read_image": ReadImageTool,
    "execute_shell": ExecuteShellTool,
    "search_web": WebSearchTool,
}


def get_tool(name: str) -> BaseTool | None:
    """Get tool instance by name.
    
    Args:
        name: Tool name.
        
    Returns:
        Tool instance or None.
    """
    tool_class = TOOLS.get(name)
    if tool_class is None:
        return None
    return tool_class()


def get_all_tools() -> list[BaseTool]:
    """Get all available tools.
    
    Returns:
        List of tool instances.
    """
    return [cls() for cls in TOOLS.values()]


__all__ = [
    "BaseTool",
    "ToolResult",
    "get_tool",
    "get_all_tools",
    "TOOLS",
]
