"""Patch-first file editing pipeline."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable

from aries.core.workspace import resolve_and_validate_path


@dataclass
class PatchResult:
    success: bool
    message: str
    artifact: dict[str, str] | None = None


class FileEditPipeline:
    """Apply deterministic patch-first edits with path validation."""

    def __init__(
        self,
        *,
        workspace: Path | None = None,
        allowed_paths: Iterable[Path] | None = None,
        denied_paths: Iterable[Path] | None = None,
        artifact_dir: Path | None = None,
    ) -> None:
        self.workspace = workspace
        self.allowed_paths = list(allowed_paths or [])
        self.denied_paths = list(denied_paths or [])
        self.artifact_dir = artifact_dir

    def read_file(self, path: str) -> str:
        resolved = resolve_and_validate_path(
            path,
            workspace=self.workspace,
            allowed_paths=self.allowed_paths,
            denied_paths=self.denied_paths,
        )
        return resolved.read_text(encoding="utf-8")

    def propose_patch(self, path: str, content: str, intent: str) -> str:
        original = ""
        resolved = resolve_and_validate_path(
            path,
            workspace=self.workspace,
            allowed_paths=self.allowed_paths,
            denied_paths=self.denied_paths,
        )
        if resolved.exists():
            original = resolved.read_text(encoding="utf-8")
        diff = _unified_diff(original, content, path)
        header = f"# Intent: {intent}\n"
        return header + diff

    def apply_patch(
        self,
        path: str,
        diff: str,
        *,
        approve_destructive: Callable[[], bool] | None = None,
    ) -> PatchResult:
        try:
            resolved = resolve_and_validate_path(
                path,
                workspace=self.workspace,
                allowed_paths=self.allowed_paths,
                denied_paths=self.denied_paths,
            )
        except Exception as exc:
            return PatchResult(False, str(exc))
        original = resolved.read_text(encoding="utf-8") if resolved.exists() else ""
        hunks = _parse_unified_diff(diff)
        if resolved.exists() and any(hunk.deletions for hunk in hunks):
            if approve_destructive and not approve_destructive():
                return PatchResult(False, "Destructive patch rejected")
        try:
            new_content = _apply_hunks(original, hunks)
        except ValueError as exc:
            return PatchResult(False, str(exc))

        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(new_content, encoding="utf-8")
        artifact = self._record_artifact(diff)
        return PatchResult(True, "Patch applied", artifact)

    def verify_patch(self, path: str, expected_markers: Iterable[str]) -> bool:
        content = self.read_file(path)
        return all(marker in content for marker in expected_markers)

    def _record_artifact(self, diff: str) -> dict[str, str] | None:
        if not self.artifact_dir:
            return None
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        artifact_path = self.artifact_dir / f"patch_{timestamp}.diff"
        artifact_path.write_text(diff, encoding="utf-8")
        return {
            "path": str(artifact_path),
            "type": "diff",
            "description": "Patch applied by file edit pipeline",
        }


@dataclass
class _Hunk:
    start_original: int
    length_original: int
    start_new: int
    length_new: int
    lines: list[str]

    @property
    def deletions(self) -> bool:
        return any(line.startswith("-") and not line.startswith("---") for line in self.lines)


_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def _parse_unified_diff(diff: str) -> list[_Hunk]:
    lines = diff.splitlines()
    hunks: list[_Hunk] = []
    current: _Hunk | None = None
    for line in lines:
        if line.startswith("# "):
            continue
        if line.startswith("@@ "):
            match = _HUNK_RE.match(line)
            if not match:
                raise ValueError("Invalid hunk header")
            if current:
                hunks.append(current)
            start_original = int(match.group(1))
            length_original = int(match.group(2) or "1")
            start_new = int(match.group(3))
            length_new = int(match.group(4) or "1")
            current = _Hunk(start_original, length_original, start_new, length_new, [])
            continue
        if line.startswith("---") or line.startswith("+++"):
            continue
        if current:
            current.lines.append(line)
    if current:
        hunks.append(current)
    if not hunks:
        raise ValueError("No hunks found in diff")
    return hunks


def _apply_hunks(original: str, hunks: list[_Hunk]) -> str:
    original_lines = original.splitlines()
    new_lines: list[str] = []
    index = 0
    for hunk in hunks:
        start = max(hunk.start_original - 1, 0)
        if start < index:
            raise ValueError("Overlapping hunks")
        new_lines.extend(original_lines[index:start])
        index = start
        for line in hunk.lines:
            if line.startswith(" "):
                expected = line[1:]
                if index >= len(original_lines) or original_lines[index] != expected:
                    raise ValueError("Patch context mismatch")
                new_lines.append(expected)
                index += 1
            elif line.startswith("-"):
                expected = line[1:]
                if index >= len(original_lines) or original_lines[index] != expected:
                    raise ValueError("Patch deletion mismatch")
                index += 1
            elif line.startswith("+"):
                new_lines.append(line[1:])
    new_lines.extend(original_lines[index:])
    return "\n".join(new_lines) + ("\n" if original.endswith("\n") or not original else "")


def _unified_diff(original: str, updated: str, path: str) -> str:
    import difflib

    original_lines = original.splitlines(keepends=True)
    updated_lines = updated.splitlines(keepends=True)
    diff_lines = difflib.unified_diff(
        original_lines,
        updated_lines,
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
    )
    return "".join(diff_lines)
