"""
Shell execution tool for Aries.
"""

import asyncio
from pathlib import Path
from typing import Any

from aries.tools.base import BaseTool, ToolResult
from aries.exceptions import ShellToolError


class ExecuteShellTool(BaseTool):
    """Execute shell commands."""
    
    name = "execute_shell"
    description = "Execute a shell command and return the output"
    
    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "Shell command to execute",
                },
                "cwd": {
                    "type": "string",
                    "description": "Working directory for the command",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds (default: 30)",
                    "default": 30,
                },
            },
            "required": ["command"],
        }
    
    async def execute(
        self,
        command: str,
        cwd: str | None = None,
        timeout: int = 30,
        **kwargs: Any,
    ) -> ToolResult:
        """Execute shell command.
        
        Args:
            command: Command to execute.
            cwd: Working directory.
            timeout: Timeout in seconds.
            
        Returns:
            ToolResult with command output.
        """
        try:
            # Resolve working directory
            working_dir = None
            if cwd:
                working_dir = Path(cwd).expanduser().resolve()
                if not working_dir.exists():
                    return ToolResult(
                        success=False,
                        content="",
                        error=f"Working directory not found: {cwd}",
                    )
            
            # Create subprocess
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=working_dir,
            )
            
            # Wait with timeout
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=timeout,
                )
            except asyncio.TimeoutError:
                process.kill()
                return ToolResult(
                    success=False,
                    content="",
                    error=f"Command timed out after {timeout} seconds",
                )
            
            # Decode output
            stdout_str = stdout.decode("utf-8", errors="replace")
            stderr_str = stderr.decode("utf-8", errors="replace")
            
            # Combine output
            output_parts = []
            if stdout_str:
                output_parts.append(stdout_str)
            if stderr_str:
                output_parts.append(f"[stderr]\n{stderr_str}")
            
            content = "\n".join(output_parts) if output_parts else "(no output)"
            
            return ToolResult(
                success=process.returncode == 0,
                content=content,
                error=None if process.returncode == 0 else f"Exit code: {process.returncode}",
                metadata={
                    "return_code": process.returncode,
                    "command": command,
                },
            )
        except Exception as e:
            return ToolResult(
                success=False,
                content="",
                error=f"Failed to execute command: {e}",
            )
