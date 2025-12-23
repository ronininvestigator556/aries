"""
Document retriever for RAG.

Retrieves relevant document chunks from ChromaDB based on query similarity.
"""

from dataclasses import dataclass
from typing import Any

try:
    import chromadb
except ImportError:
    chromadb = None

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
        self._last_results: list[RetrievedChunk] = []
        self._last_handles: list[str] = []
    
    async def load_index(self, name: str) -> bool:
        """Load an index for retrieval.
        
        Args:
            name: Name of index to load.
            
        Returns:
            True if loaded successfully.
        """
        if chromadb is None:
            raise ImportError("ChromaDB is not installed. Please install it to use RAG features.")

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
        ids = result.get("ids", [[]])[0] if "ids" in result else []

        handles: list[str] = []
        for doc, meta, dist, chunk_id in zip(docs, metadatas, distances, ids):
            handle = f"{self._current_index}:{meta.get('chunk_id')}"
            handles.append(handle)
            chunks.append(
                RetrievedChunk(
                    content=doc,
                    source=str(meta.get("source")),
                    score=float(dist) if dist is not None else 0.0,
                    metadata=meta,
                )
            )
        self._last_results = chunks
        self._last_handles = handles
        return chunks
    
    def unload(self) -> None:
        """Unload the current index."""
        self._current_index = None
        self._collection = None
        self._last_results = []
        self._last_handles = []

    @property
    def current_index(self) -> str | None:
        """Get currently loaded index name."""
        return self._current_index

    @property
    def last_results(self) -> list[RetrievedChunk]:
        return self._last_results

    @property
    def last_handles(self) -> list[str]:
        return self._last_handles

    def get_handle(self, handle: str) -> RetrievedChunk | None:
        """Lookup a retrieved chunk by handle from last retrieval."""
        try:
            index, chunk_id = handle.split(":")
        except ValueError:
            return None
        if index != self._current_index:
            return None
        for chunk in self._last_results:
            if str(chunk.metadata.get("chunk_id")) == chunk_id:
                return chunk
        return None
