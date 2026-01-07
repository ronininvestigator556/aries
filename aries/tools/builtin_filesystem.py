"""
Builtin filesystem tools for Aries.
"""

from __future__ import annotations

import fnmatch
from pathlib import Path
from typing import Any

from aries.core.file_edit import FileEditPipeline
from aries.core.workspace import resolve_and_validate_path
from aries.tools.base import BaseTool, ToolResult


def _sorted_paths(paths: list[Path]) -> list[Path]:
    return sorted(paths, key=lambda path: str(path).lower())


class BuiltinListDirTool(BaseTool):
    name = "list_dir"
    description = "List files and directories at a path."
    risk_level = "read"
    path_params = ("path",)
    uses_filesystem_paths = True
    emits_artifacts = False

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Directory path to list"},
                "recursive": {
                    "type": "boolean",
                    "description": "Whether to list recursively",
                    "default": False,
                },
                "glob": {
                    "type": "string",
                    "description": "Optional glob filter for entries",
                },
                "max_entries": {
                    "type": "integer",
                    "description": "Maximum number of entries to return",
                    "default": 200,
                    "minimum": 1,
                },
            },
            "required": ["path"],
        }

    async def execute(
        self,
        path: str,
        recursive: bool = False,
        glob: str | None = None,
        max_entries: int = 200,
        **kwargs: Any,
    ) -> ToolResult:
        try:
            resolved = resolve_and_validate_path(
                path,
                workspace=kwargs.get("workspace"),
                allowed_paths=kwargs.get("allowed_paths"),
                denied_paths=kwargs.get("denied_paths"),
            )
            if not resolved.exists():
                return ToolResult(False, "", error=f"Path not found: {path}")
            if not resolved.is_dir():
                return ToolResult(False, "", error=f"Not a directory: {path}")

            entries: list[Path] = []
            if recursive:
                entries = [p for p in resolved.rglob("*") if p.exists()]
            else:
                entries = list(resolved.iterdir())

            if glob:
                entries = [p for p in entries if fnmatch.fnmatch(p.name, glob)]

            entries = _sorted_paths(entries)
            truncated = len(entries) > max_entries
            entries = entries[:max_entries]
            content = "\n".join(str(p) for p in entries)
            return ToolResult(
                True,
                content,
                metadata={
                    "path": str(resolved),
                    "entry_count": len(entries),
                    "truncated": truncated,
                },
            )
        except Exception as exc:
            return ToolResult(False, "", error=str(exc))


class BuiltinReadTextTool(BaseTool):
    name = "read_text"
    description = "Read a text file with optional truncation."
    risk_level = "read"
    path_params = ("path",)
    uses_filesystem_paths = True
    emits_artifacts = False

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path to read"},
                "max_bytes": {
                    "type": "integer",
                    "description": "Maximum bytes to read",
                    "minimum": 1,
                },
            },
            "required": ["path"],
        }

    async def execute(self, path: str, max_bytes: int | None = None, **kwargs: Any) -> ToolResult:
        try:
            resolved = resolve_and_validate_path(
                path,
                workspace=kwargs.get("workspace"),
                allowed_paths=kwargs.get("allowed_paths"),
                denied_paths=kwargs.get("denied_paths"),
            )
            if not resolved.exists():
                return ToolResult(False, "", error=f"File not found: {path}")
            if not resolved.is_file():
                return ToolResult(False, "", error=f"Not a file: {path}")

            data = resolved.read_bytes()
            truncated = False
            if max_bytes is not None and len(data) > max_bytes:
                data = data[:max_bytes]
                truncated = True
            text = data.decode("utf-8", errors="replace")
            return ToolResult(
                True,
                text,
                metadata={
                    "path": str(resolved),
                    "size": resolved.stat().st_size,
                    "bytes_read": len(data),
                    "truncated": truncated,
                },
            )
        except Exception as exc:
            return ToolResult(False, "", error=str(exc))


class BuiltinWriteTextTool(BaseTool):
    name = "write_text"
    description = "Write text to a file."
    mutates_state = True
    emits_artifacts = True
    risk_level = "write"
    path_params = ("path",)
    uses_filesystem_paths = True

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path to write"},
                "content": {"type": "string", "description": "Content to write"},
                "overwrite": {
                    "type": "boolean",
                    "description": "Overwrite file if it exists",
                    "default": True,
                },
            },
            "required": ["path", "content"],
        }

    async def execute(
        self,
        path: str,
        content: str,
        overwrite: bool = True,
        **kwargs: Any,
    ) -> ToolResult:
        try:
            resolved = resolve_and_validate_path(
                path,
                workspace=kwargs.get("workspace"),
                allowed_paths=kwargs.get("allowed_paths"),
                denied_paths=kwargs.get("denied_paths"),
            )
            if resolved.exists() and not overwrite:
                return ToolResult(False, "", error=f"File exists and overwrite is false: {path}")

            resolved.parent.mkdir(parents=True, exist_ok=True)
            resolved.write_text(content, encoding="utf-8")
            artifact = {
                "path": str(resolved),
                "type": "file",
                "name": resolved.name,
                "description": "File written by fs:write_text",
            }
            return ToolResult(
                True,
                f"Wrote {path}",
                metadata={"path": str(resolved), "bytes_written": len(content)},
                artifacts=[artifact],
            )
        except Exception as exc:
            return ToolResult(False, "", error=str(exc))


class BuiltinSearchTextTool(BaseTool):
    name = "search_text"
    description = "Search for text within files under a root directory."
    risk_level = "read"
    path_params = ("root",)
    uses_filesystem_paths = True
    emits_artifacts = False

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "root": {"type": "string", "description": "Root directory to search"},
                "query": {"type": "string", "description": "Text to search for"},
                "max_hits": {
                    "type": "integer",
                    "description": "Maximum number of matches",
                    "default": 20,
                    "minimum": 1,
                },
                "context_chars": {
                    "type": "integer",
                    "description": "Context chars around match",
                    "default": 80,
                    "minimum": 0,
                },
            },
            "required": ["root", "query"],
        }

    async def execute(
        self,
        root: str,
        query: str,
        max_hits: int = 20,
        context_chars: int = 80,
        **kwargs: Any,
    ) -> ToolResult:
        try:
            resolved_root = resolve_and_validate_path(
                root,
                workspace=kwargs.get("workspace"),
                allowed_paths=kwargs.get("allowed_paths"),
                denied_paths=kwargs.get("denied_paths"),
            )
            if not resolved_root.exists():
                return ToolResult(False, "", error=f"Root not found: {root}")
            if not resolved_root.is_dir():
                return ToolResult(False, "", error=f"Not a directory: {root}")

            hits: list[dict[str, Any]] = []
            files = _sorted_paths([p for p in resolved_root.rglob("*") if p.is_file()])
            for file_path in files:
                try:
                    text = file_path.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    continue
                for line_no, line in enumerate(text.splitlines(), start=1):
                    if query not in line:
                        continue
                    idx = line.find(query)
                    start = max(idx - context_chars, 0)
                    end = min(idx + len(query) + context_chars, len(line))
                    snippet = line[start:end]
                    hits.append(
                        {
                            "path": str(file_path),
                            "line": line_no,
                            "snippet": snippet,
                        }
                    )
                    if len(hits) >= max_hits:
                        break
                if len(hits) >= max_hits:
                    break

            content = "\n".join(
                f"{hit['path']}:{hit['line']}:{hit['snippet']}" for hit in hits
            )
            return ToolResult(
                True,
                content,
                metadata={
                    "root": str(resolved_root),
                    "hits": len(hits),
                    "truncated": len(hits) >= max_hits,
                },
            )
        except Exception as exc:
            return ToolResult(False, "", error=str(exc))


class BuiltinApplyPatchTool(BaseTool):
    name = "apply_patch"
    description = "Apply a unified diff patch to a file."
    mutates_state = True
    emits_artifacts = True
    risk_level = "write"
    path_params = ("path",)
    uses_filesystem_paths = True

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path to patch"},
                "unified_diff": {
                    "type": "string",
                    "description": "Unified diff to apply",
                },
            },
            "required": ["path", "unified_diff"],
        }

    async def execute(self, path: str, unified_diff: str, **kwargs: Any) -> ToolResult:
        pipeline = FileEditPipeline(
            workspace=kwargs.get("workspace"),
            allowed_paths=kwargs.get("allowed_paths"),
            denied_paths=kwargs.get("denied_paths"),
            artifact_dir=getattr(kwargs.get("workspace"), "artifact_dir", None),
        )
        result = pipeline.apply_patch(path, unified_diff)
        if not result.success:
            return ToolResult(False, "", error=result.message)
        artifacts = [result.artifact] if result.artifact else None
        return ToolResult(
            True,
            result.message,
            metadata={"path": path},
            artifacts=artifacts,
        )
