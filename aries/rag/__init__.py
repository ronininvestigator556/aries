"""
RAG (Retrieval Augmented Generation) module for Aries.

This module provides document indexing and retrieval capabilities
using ChromaDB as the vector store and Ollama for embeddings.
"""

from importlib import import_module

__all__ = ["Indexer", "Retriever"]


def __getattr__(name: str):
    if name not in __all__:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(f"aries.rag.{name.lower()}")
    return getattr(module, name)


def __dir__():
    return sorted(__all__)
