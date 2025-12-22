"""
Document indexer for RAG.

Indexes documents into ChromaDB for later retrieval.
"""

from pathlib import Path
from typing import Any

try:
    import chromadb
except ImportError:
    chromadb = None

import hashlib

from aries.config import RAGConfig
from aries.exceptions import DocumentLoadError, IndexError
from aries.core.ollama_client import OllamaClient
from aries.rag.chunker import TextChunker
from aries.rag.loaders import LOADERS, BaseLoader, Document


class Indexer:
    """Index documents into ChromaDB."""
    
    def __init__(
        self, 
        config: RAGConfig,
        ollama: OllamaClient,
    ) -> None:
        """Initialize indexer.
        
        Args:
            config: RAG configuration.
            ollama: Ollama client for embeddings.
        """
        self.config = config
        self.ollama = ollama
        self._collection = None
        self._chunker = TextChunker(
            chunk_size=config.chunk_size,
            chunk_overlap=config.chunk_overlap,
        )
    
    async def index_directory(
        self,
        path: Path,
        name: str,
        force: bool = False,
    ) -> dict[str, Any]:
        """Index all documents in a directory.
        
        Args:
            path: Path to directory containing documents.
            name: Name for this index.
            force: Whether to overwrite existing index.
            
        Returns:
            Dictionary with indexing statistics.
        """
        directory = Path(path).expanduser()
        if not directory.exists() or not directory.is_dir():
            raise IndexError(f"Directory not found: {path}")

        client = self._get_client()

        if force:
            client.delete_collection(name)

        collection = client.get_or_create_collection(name=name)
        documents = await self._load_documents_from_dir(directory)

        chunk_texts: list[str] = []
        metadatas: list[dict[str, Any]] = []
        ids: list[str] = []

        for doc in documents:
            chunks = self._chunker.chunk(doc.content)
            if not chunks:
                continue
            for chunk in chunks:
                chunk_hash = hashlib.sha256(chunk.content.encode("utf-8")).hexdigest()
                chunk_texts.append(chunk.content)
                meta = dict(doc.metadata)
                meta["source"] = doc.source
                meta["chunk_id"] = chunk.chunk_id
                meta["tokens"] = chunk.token_count
                meta["start_offset"] = chunk.start_offset
                meta["end_offset"] = chunk.end_offset
                meta["hash"] = chunk_hash
                embedding_model = getattr(
                    getattr(self.ollama, "config", None), "embedding_model", None
                )
                meta["embedding_model"] = embedding_model or "unknown"
                metadatas.append(meta)
                ids.append(f"{doc.source}#chunk={chunk.chunk_id}")

        embeddings = [
            await self.ollama.generate_embedding(text)
            for text in chunk_texts
        ]

        collection.upsert(
            documents=chunk_texts,
            embeddings=embeddings,
            metadatas=metadatas,
            ids=ids,
        )

        self._collection = collection
        return {
            "name": name,
            "documents_indexed": len(documents),
        }
    
    async def index_file(
        self,
        path: Path,
        index_name: str,
    ) -> dict[str, Any]:
        """Index a single file.
        
        Args:
            path: Path to file.
            index_name: Name of index to add to.
            
        Returns:
            Dictionary with indexing statistics.
        """
        return await self.index_directory(path.parent, index_name)
    
    def list_indices(self) -> list[str]:
        """List available indices.
        
        Returns:
            List of index names.
        """
        indices_dir = Path(self.config.indices_dir)
        if not indices_dir.exists():
            return []
        return [d.name for d in indices_dir.iterdir() if d.is_dir()]

    async def _load_documents_from_dir(self, directory: Path) -> list[Document]:
        """Load supported documents from a directory."""
        documents: list[Document] = []

        loaders: list[BaseLoader] = [loader() for loader in LOADERS]
        supported_ext = {ext for loader in loaders for ext in loader.extensions}

        for file_path in directory.rglob("*"):
            if not file_path.is_file() or file_path.suffix.lower() not in supported_ext:
                continue

            loader = next((ld for ld in loaders if ld.can_load(file_path)), None)
            if loader is None:
                continue

            try:
                loaded = await loader.load(file_path)
            except DocumentLoadError:
                continue

            documents.extend(loaded)

        return documents

    def _get_client(self) -> "chromadb.ClientAPI":
        """Create a ChromaDB client using configured indices directory."""
        if chromadb is None:
            raise ImportError("ChromaDB is not installed. Please install it to use RAG features.")
            
        indices_dir = Path(self.config.indices_dir)
        indices_dir.mkdir(parents=True, exist_ok=True)
        return chromadb.PersistentClient(path=str(indices_dir))
