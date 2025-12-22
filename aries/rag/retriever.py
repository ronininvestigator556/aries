"""
Document retriever for RAG.

Retrieves relevant document chunks from ChromaDB based on query similarity.
"""

from dataclasses import dataclass
from typing import Any

import chromadb

from aries.config import RAGConfig
from aries.core.ollama_client import OllamaClient


@dataclass
class RetrievedChunk:
    """A retrieved document chunk."""
    
    content: str
    source: str
    score: float
    metadata: dict[str, Any]


class Retriever:
    """Retrieve relevant documents from an index."""
    
    def __init__(
        self,
        config: RAGConfig,
        ollama: OllamaClient,
    ) -> None:
        """Initialize retriever.
        
        Args:
            config: RAG configuration.
            ollama: Ollama client for embeddings.
        """
        self.config = config
        self.ollama = ollama
        self._current_index: str | None = None
        self._collection = None
    
    async def load_index(self, name: str) -> bool:
        """Load an index for retrieval.
        
        Args:
            name: Name of index to load.
            
        Returns:
            True if loaded successfully.
        """
        client = chromadb.PersistentClient(path=str(self.config.indices_dir))
        try:
            self._collection = client.get_collection(name=name)
        except Exception as exc:
            raise FileNotFoundError(f"Index not found: {name}") from exc

        self._current_index = name
        return True
    
    async def retrieve(
        self,
        query: str,
        top_k: int | None = None,
    ) -> list[RetrievedChunk]:
        """Retrieve relevant chunks for a query.
        
        Args:
            query: Search query.
            top_k: Number of results (uses config default if not specified).
            
        Returns:
            List of retrieved chunks sorted by relevance.
        """
        if not self._collection:
            raise FileNotFoundError("No index loaded")

        top_k = top_k or self.config.top_k
        embedding = await self.ollama.generate_embedding(query)
        result = self._collection.query(
            query_embeddings=[embedding],
            n_results=top_k,
        )

        chunks: list[RetrievedChunk] = []
        docs = result.get("documents", [[]])[0]
        metadatas = result.get("metadatas", [[]])[0]
        distances = result.get("distances", [[]])[0] if "distances" in result else []

        for doc, meta, dist in zip(docs, metadatas, distances):
            chunks.append(
                RetrievedChunk(
                    content=doc,
                    source=str(meta.get("source")),
                    score=float(dist) if dist is not None else 0.0,
                    metadata=meta,
                )
            )

        return chunks
    
    def unload(self) -> None:
        """Unload the current index."""
        self._current_index = None
        self._collection = None
    
    @property
    def current_index(self) -> str | None:
        """Get currently loaded index name."""
        return self._current_index
