"""
Document loaders for RAG.

Each loader handles a specific file format and returns Document objects.
"""

from aries.rag.loaders.base import BaseLoader, Document
from aries.rag.loaders.text import TextLoader

LOADERS: list[type[BaseLoader]] = [
    TextLoader,
]

__all__ = ["BaseLoader", "Document", "LOADERS", "TextLoader"]
