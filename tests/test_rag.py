from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

try:
    import chromadb
except ImportError:
    chromadb = None

from aries.config import RAGConfig
from aries.core.ollama_client import OllamaClient
from aries.rag.indexer import Indexer
from aries.rag.retriever import Retriever


class DummyOllama(OllamaClient):
    def __init__(self):
        pass

    async def generate_embedding(self, text: str, model: str | None = None):
        return [float(len(text))]


@pytest.mark.skipif(chromadb is None, reason="ChromaDB not installed")
@pytest.mark.anyio
async def test_index_and_retrieve(tmp_path: Path):
    cfg = RAGConfig(indices_dir=tmp_path, top_k=2)
    dummy = DummyOllama()
    indexer = Indexer(cfg, dummy)

    sample_dir = tmp_path / "docs"
    sample_dir.mkdir()
    (sample_dir / "a.txt").write_text("alpha", encoding="utf-8")
    (sample_dir / "b.txt").write_text("beta", encoding="utf-8")

    stats = await indexer.index_directory(sample_dir, name="test_index")
    assert stats["documents_indexed"] == 2

    retriever = Retriever(cfg, dummy)
    await retriever.load_index("test_index")
    results = await retriever.retrieve("alpha", top_k=1)
    assert results
    assert "alpha" in results[0].content
