from __future__ import annotations

import pytest

from aries.config import Config
from aries.core.ollama_client import OllamaClient


class FakeAsyncStream:
    def __init__(self, chunks):
        self._chunks = chunks

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._chunks:
            raise StopAsyncIteration
        return self._chunks.pop(0)


class FakeAsyncClient:
    def __init__(self, host: str):
        self.host = host

    async def list(self):
        return {"models": [{"name": "llama3.2:latest"}]}

    async def chat(self, model: str, messages: list[dict], stream: bool | None = None, **kwargs):
        if stream:
            return FakeAsyncStream(
                [{"message": {"content": "Hello"}}, {"message": {"content": " world"}}]
            )
        return {"message": {"content": f"Reply from {model}"}}


@pytest.mark.anyio
async def test_list_models(monkeypatch):
    config = Config().ollama
    monkeypatch.setattr("aries.core.ollama_client.AsyncClient", FakeAsyncClient)
    client = OllamaClient(config)

    models = await client.get_model_names()
    assert "llama3.2:latest" in models


@pytest.mark.anyio
async def test_chat_and_stream(monkeypatch):
    config = Config().ollama
    monkeypatch.setattr("aries.core.ollama_client.AsyncClient", FakeAsyncClient)
    client = OllamaClient(config)

    content = await client.chat(model="llama3.2", messages=[])
    assert "Reply from llama3.2" in content
    raw = await client.chat(model="llama3.2", messages=[], raw=True)
    assert isinstance(raw, dict)

    collected = []
    async for chunk in client.chat_stream(model="llama3.2", messages=[]):
        collected.append(chunk)
    assert "".join(collected) == "Hello world"
