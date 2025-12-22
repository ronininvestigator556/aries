from __future__ import annotations

import base64
from pathlib import Path

import pytest

from aries.tools.filesystem import ListDirectoryTool, ReadFileTool, WriteFileTool
from aries.tools.image import ReadImageTool
from aries.tools.shell import ExecuteShellTool


@pytest.mark.anyio
async def test_read_and_write_file(temp_file: Path) -> None:
    writer = WriteFileTool()
    write_result = await writer.execute(path=temp_file, content="updated", mode="write")
    assert write_result.success

    reader = ReadFileTool()
    read_result = await reader.execute(path=temp_file)
    assert read_result.success
    assert read_result.content == "updated"


@pytest.mark.anyio
async def test_list_directory(temp_file: Path) -> None:
    lister = ListDirectoryTool()
    result = await lister.execute(path=temp_file.parent)
    assert result.success
    assert "sample.txt" in result.content


@pytest.mark.anyio
async def test_execute_shell() -> None:
    tool = ExecuteShellTool()
    result = await tool.execute(command="echo hello")
    assert result.success
    assert "hello" in result.content


@pytest.mark.anyio
async def test_read_image(temp_image: Path) -> None:
    tool = ReadImageTool()
    result = await tool.execute(path=temp_image)
    assert result.success
    decoded = base64.b64decode(result.content)
    assert decoded == temp_image.read_bytes()
