"""
RAG (Retrieval Augmented Generation) module for Aries.

This module provides document indexing and retrieval capabilities
using ChromaDB as the vector store and Ollama for embeddings.
"""

from aries.rag.indexer import Indexer
from aries.rag.retriever import Retriever

__all__ = ["Indexer", "Retriever"]
