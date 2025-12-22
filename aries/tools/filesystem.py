"""
File system tools for Aries.
"""

import mimetypes
import os
from pathlib import Path
from typing import Any

import aiofiles

from aries.tools.base import BaseTool, ToolResult
from aries.exceptions import FileToolError


class ReadFileTool(BaseTool):
    """Read contents of a file."""
    
    name = "read_file"
    description = "Read the contents of a file at the specified path"
    risk_level = "read"
    path_params = ("path",)
    
    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the file to read",
                },
                "encoding": {
                    "type": "string",
                    "description": "File encoding (default: utf-8)",
                    "default": "utf-8",
                },
            },
            "required": ["path"],
        }
    
    async def execute(self, path: str, encoding: str = "utf-8", **kwargs: Any) -> ToolResult:
        """Read file contents.
        
        Args:
            path: File path.
            encoding: Text encoding.
            
        Returns:
            ToolResult with file contents.
        """
        try:
            file_path = Path(path).expanduser().resolve()
            
            if not file_path.exists():
                return ToolResult(
                    success=False,
                    content="",
                    error=f"File not found: {path}",
                )
            
            if not file_path.is_file():
                return ToolResult(
                    success=False,
                    content="",
                    error=f"Not a file: {path}",
                )
            
            async with aiofiles.open(file_path, "r", encoding=encoding) as f:
                content = await f.read()
            
            return ToolResult(
                success=True,
                content=content,
                metadata={"path": str(file_path), "size": file_path.stat().st_size},
            )
        except Exception as e:
            return ToolResult(
                success=False,
                content="",
                error=f"Failed to read file: {e}",
            )



class WriteFileTool(BaseTool):
    """Write content to a file."""
    
    name = "write_file"
    description = "Write content to a file, creating it if it doesn't exist"
    mutates_state = True
    emits_artifacts = True
    risk_level = "write"
    path_params = ("path",)
    
    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the file to write",
                },
                "content": {
                    "type": "string",
                    "description": "Content to write to the file",
                },
                "mode": {
                    "type": "string",
                    "enum": ["write", "append"],
                    "description": "Write mode: 'write' (overwrite) or 'append'",
                    "default": "write",
                },
            },
            "required": ["path", "content"],
        }
    
    async def execute(
        self, 
        path: str, 
        content: str, 
        mode: str = "write",
        **kwargs: Any,
    ) -> ToolResult:
        """Write content to file.
        
        Args:
            path: File path.
            content: Content to write.
            mode: 'write' or 'append'.
            
        Returns:
            ToolResult with success status.
        """
        try:
            file_path = Path(path).expanduser().resolve()
            file_mode = "w" if mode == "write" else "a"
            
            # Create parent directories if needed
            file_path.parent.mkdir(parents=True, exist_ok=True)
            
            async with aiofiles.open(file_path, file_mode, encoding="utf-8") as f:
                await f.write(content)
            
            mime_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
            return ToolResult(
                success=True,
                content=f"Successfully wrote to {path}",
                metadata={
                    "path": str(file_path),
                    "bytes_written": len(content),
                    "artifact": {
                        "path": str(file_path),
                        "type": "file",
                        "name": file_path.name,
                        "description": "File created by write_file",
                        "mime": mime_type,
                    },
                },
            )
        except Exception as e:
            return ToolResult(
                success=False,
                content="",
                error=f"Failed to write file: {e}",
            )


class ListDirectoryTool(BaseTool):
    """List contents of a directory."""
    
    name = "list_directory"
    description = "List files and directories at the specified path"
    risk_level = "read"
    path_params = ("path",)
    
    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the directory to list",
                },
                "recursive": {
                    "type": "boolean",
                    "description": "Whether to list recursively",
                    "default": False,
                },
                "pattern": {
                    "type": "string",
                    "description": "Glob pattern to filter files (e.g., '*.py')",
                    "default": "*",
                },
            },
            "required": ["path"],
        }
    
    async def execute(
        self,
        path: str,
        recursive: bool = False,
        pattern: str = "*",
        **kwargs: Any,
    ) -> ToolResult:
        """List directory contents.
        
        Args:
            path: Directory path.
            recursive: List recursively.
            pattern: Glob pattern.
            
        Returns:
            ToolResult with file listing.
        """
        try:
            dir_path = Path(path).expanduser().resolve()
            
            if not dir_path.exists():
                return ToolResult(
                    success=False,
                    content="",
                    error=f"Directory not found: {path}",
                )
            
            if not dir_path.is_dir():
                return ToolResult(
                    success=False,
                    content="",
                    error=f"Not a directory: {path}",
                )
            
            if recursive:
                entries = list(dir_path.rglob(pattern))
            else:
                entries = list(dir_path.glob(pattern))
            
            # Format output
            lines = []
            for entry in sorted(entries):
                rel_path = entry.relative_to(dir_path)
                prefix = "[DIR] " if entry.is_dir() else "[FILE]"
                lines.append(f"{prefix} {rel_path}")
            
            content = "\n".join(lines) if lines else "(empty directory)"
            
            return ToolResult(
                success=True,
                content=content,
                metadata={"path": str(dir_path), "count": len(entries)},
            )
        except Exception as e:
            return ToolResult(
                success=False,
                content="",
                error=f"Failed to list directory: {e}",
            )
