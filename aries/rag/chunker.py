"""
Text chunking utilities for RAG.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import tiktoken


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
    ) -> None:
        self.chunk_size = chunk_size
        self.chunk_overlap = min(chunk_overlap, chunk_size - 1) if chunk_size > 1 else 0
        try:
            self._encoder = tiktoken.get_encoding(encoding)
        except Exception:
            self._encoder = tiktoken.get_encoding("cl100k_base")

    def chunk(self, text: str) -> list[Chunk]:
        """Chunk text into overlapping windows."""
        tokens = self._encoder.encode(text or "")
        if not tokens:
            return []

        step = max(self.chunk_size - self.chunk_overlap, 1)
        chunks: list[Chunk] = []
        for idx, start in enumerate(range(0, len(tokens), step)):
            window = tokens[start : start + self.chunk_size]
            if not window:
                continue
            content = self._encoder.decode(window)
            chunks.append(
                Chunk(
                    content=content,
                    token_count=len(window),
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
) -> list[Chunk]:
    """Convenience function to chunk multiple texts."""
    chunker = TextChunker(chunk_size=chunk_size, chunk_overlap=chunk_overlap, encoding=encoding)
    result: list[Chunk] = []
    for text in texts:
        result.extend(chunker.chunk(text))
    return result
