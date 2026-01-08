from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from aries.config import Config
from aries.core.workspace import WorkspaceManager
from aries.tools.builtin_web import (
    BuiltinWebExtractTool,
    BuiltinWebFetchTool,
    BuiltinWebSearchTool,
)


@pytest.mark.asyncio
async def test_web_search_returns_ranked_results() -> None:
    tool = BuiltinWebSearchTool()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/search")
        data = {
            "results": [
                {"title": "One", "url": "https://example.com/1", "content": "First"},
                {"title": "Two", "url": "https://example.com/2", "content": "Second"},
            ]
        }
        return httpx.Response(200, json=data)

    transport = httpx.MockTransport(handler)
    result = await tool.execute(query="example", top_k=2, transport=transport)

    assert result.success is True
    payload = json.loads(result.content)
    results = payload["data"]["results"]
    assert results[0]["rank"] == 1
    assert results[1]["rank"] == 2
    assert results[0]["url"] == "https://example.com/1"


@pytest.mark.asyncio
async def test_web_fetch_enforces_max_bytes_and_writes_artifact(tmp_path) -> None:
    tool = BuiltinWebFetchTool()
    config = Config()
    config.workspace.root = tmp_path
    manager = WorkspaceManager(config.workspace, config.tools)
    workspace = manager.new("demo")

    body = b"0123456789"

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            content=body,
        )

    transport = httpx.MockTransport(handler)
    result = await tool.execute(
        url="https://example.com",
        max_bytes=5,
        timeout_seconds=5,
        workspace=workspace,
        transport=transport,
    )

    assert result.success is True
    payload = json.loads(result.content)
    data = payload["data"]
    assert data["bytes_read"] == 5
    assert data["truncated"] is True
    artifact_path = data["artifact_ref"]
    assert artifact_path
    assert len(Path(artifact_path).read_bytes()) == 5


@pytest.mark.asyncio
async def test_web_extract_produces_stable_text(tmp_path) -> None:
    tool = BuiltinWebExtractTool()
    artifact = tmp_path / "page.html"
    artifact.write_text(
        "<html><head><style>h1{}</style><script>bad()</script></head>"
        "<body><h1>Hello</h1><p>World</p></body></html>",
        encoding="utf-8",
    )

    result = await tool.execute(artifact_ref=str(artifact), mode="text", workspace=tmp_path)

    assert result.success is True
    payload = json.loads(result.content)
    assert payload["data"]["text"] == "Hello World"
