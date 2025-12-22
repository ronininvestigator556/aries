"""
Document loaders for RAG.

Each loader handles a specific file format and returns Document objects.
"""

from aries.rag.loaders.base import BaseLoader, Document

__all__ = ["BaseLoader", "Document"]
