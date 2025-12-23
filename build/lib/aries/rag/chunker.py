"""
Text chunking utilities for RAG.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from aries.core.tokenizer import TokenEstimator


@dataclass
class Chunk:
    """A single text chunk with metadata."""

    content: str
    token_count: int
    chunk_id: int
    start_offset: int
    end_offset: int


class TextChunker:
    """Token-aware text chunker with overlap support."""

    def __init__(
        self,
        chunk_size: int = 500,
        chunk_overlap: int = 50,
        encoding: str = "cl100k_base",
        token_estimator: TokenEstimator | None = None,
    ) -> None:
        self.chunk_size = chunk_size
        self.chunk_overlap = min(chunk_overlap, chunk_size - 1) if chunk_size > 1 else 0
        self._tokenizer = token_estimator or TokenEstimator(mode="approx", encoding=encoding)

    def chunk(self, text: str) -> list[Chunk]:
        """Chunk text into overlapping windows."""
        tokens = self._tokenizer.encode(text or "")
        if not tokens:
            return []

        step = max(self.chunk_size - self.chunk_overlap, 1)
        chunks: list[Chunk] = []
        for idx, start in enumerate(range(0, len(tokens), step)):
            window = tokens[start : start + self.chunk_size]
            if not window:
                continue
            content = self._tokenizer.decode(window)
            chunks.append(
                Chunk(
                    content=content,
                    token_count=self._tokenizer.count(content),
                    chunk_id=idx,
                    start_offset=start,
                    end_offset=min(start + len(window), len(tokens)),
                )
            )
        return chunks


def chunk_documents(
    texts: Iterable[str],
    chunk_size: int,
    chunk_overlap: int,
    encoding: str = "cl100k_base",
    token_estimator: TokenEstimator | None = None,
) -> list[Chunk]:
    """Convenience function to chunk multiple texts."""
    chunker = TextChunker(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        encoding=encoding,
        token_estimator=token_estimator,
    )
    result: list[Chunk] = []
    for text in texts:
        result.extend(chunker.chunk(text))
    return result
