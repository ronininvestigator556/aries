"""
Image loading tool for vision-enabled models.
"""

import base64
from pathlib import Path
from typing import Any

import aiofiles

from aries.config import get_config
from aries.tools.base import BaseTool, ToolResult


class ReadImageTool(BaseTool):
    """Load an image file and return it as a base64 string."""
    
    name = "read_image"
    description = "Load an image file from disk and return a base64-encoded string"
    risk_level = "read"
    path_params = ("path",)
    uses_filesystem_paths = True
    
    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the image file",
                },
            },
            "required": ["path"],
        }
    
    async def execute(self, path: str, **kwargs: Any) -> ToolResult:
        """Read and encode an image file.
        
        Args:
            path: Path to the image.
            
        Returns:
            ToolResult containing base64 data.
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
            
            size_mb = file_path.stat().st_size / (1024 * 1024)
            max_size = get_config().tools.max_file_size_mb
            if size_mb > max_size:
                return ToolResult(
                    success=False,
                    content="",
                    error=f"File exceeds size limit ({max_size} MB): {size_mb:.2f} MB",
                )
            
            async with aiofiles.open(file_path, "rb") as f:
                data = await f.read()
            
            encoded = base64.b64encode(data).decode("utf-8")
            return ToolResult(
                success=True,
                content=encoded,
                metadata={
                    "path": str(file_path),
                    "size_bytes": len(data),
                },
            )
        except Exception as e:
            return ToolResult(
                success=False,
                content="",
                error=f"Failed to load image: {e}",
            )
