from __future__ import annotations

from pathlib import Path

import pytest

from aries.tools.builtin_filesystem import (
    BuiltinApplyPatchTool,
    BuiltinListDirTool,
    BuiltinReadTextTool,
    BuiltinSearchTextTool,
    BuiltinWriteTextTool,
)


@pytest.mark.anyio
async def test_list_dir_ordering_and_truncation(tmp_path: Path) -> None:
    (tmp_path / "b.txt").write_text("b", encoding="utf-8")
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")

    tool = BuiltinListDirTool()
    result = await tool.execute(path=str(tmp_path), max_entries=1, workspace=tmp_path)

    assert result.success
    assert result.metadata["truncated"] is True
    assert result.content.splitlines()[0].endswith("a.txt")


@pytest.mark.anyio
async def test_read_text_truncation(tmp_path: Path) -> None:
    target = tmp_path / "note.txt"
    target.write_text("hello world", encoding="utf-8")

    tool = BuiltinReadTextTool()
    result = await tool.execute(path=str(target), max_bytes=5, workspace=tmp_path)

    assert result.success
    assert result.content == "hello"
    assert result.metadata["truncated"] is True


@pytest.mark.anyio
async def test_write_text_respects_overwrite(tmp_path: Path) -> None:
    target = tmp_path / "note.txt"
    target.write_text("hello", encoding="utf-8")

    tool = BuiltinWriteTextTool()
    result = await tool.execute(
        path=str(target),
        content="new",
        overwrite=False,
        workspace=tmp_path,
    )

    assert result.success is False
    assert "overwrite is false" in (result.error or "")


@pytest.mark.anyio
async def test_search_text_is_deterministic(tmp_path: Path) -> None:
    first = tmp_path / "b.txt"
    second = tmp_path / "a.txt"
    first.write_text("find me", encoding="utf-8")
    second.write_text("find me too", encoding="utf-8")

    tool = BuiltinSearchTextTool()
    result = await tool.execute(root=str(tmp_path), query="find", workspace=tmp_path)

    assert result.success
    lines = result.content.splitlines()
    assert len(lines) == 2
    assert lines[0].endswith("a.txt:1:find me too")
    assert lines[1].endswith("b.txt:1:find me")


@pytest.mark.anyio
async def test_apply_patch_applies_diff(tmp_path: Path) -> None:
    target = tmp_path / "note.txt"
    target.write_text("hello\n", encoding="utf-8")
    diff = "--- a/note.txt\n+++ b/note.txt\n@@ -1 +1 @@\n-hello\n+goodbye\n"

    tool = BuiltinApplyPatchTool()
    result = await tool.execute(path=str(target), unified_diff=diff, workspace=tmp_path)

    assert result.success
    assert target.read_text(encoding="utf-8") == "goodbye\n"
