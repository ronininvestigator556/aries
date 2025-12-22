"""
Document loaders for RAG.

Each loader handles a specific file format and returns Document objects.
"""

from aries.rag.loaders.base import BaseLoader, Document
from aries.rag.loaders.epub import EPUBLoader
from aries.rag.loaders.markdown import MarkdownLoader
from aries.rag.loaders.pdf import PDFLoader
from aries.rag.loaders.text import TextLoader

LOADERS: list[type[BaseLoader]] = [
    TextLoader,
    MarkdownLoader,
    PDFLoader,
    EPUBLoader,
]

__all__ = [
    "BaseLoader",
    "Document",
    "LOADERS",
    "TextLoader",
    "MarkdownLoader",
    "PDFLoader",
    "EPUBLoader",
]
