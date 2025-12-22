"""
EPUB loader for RAG using ebooklib.
"""

from pathlib import Path
from datetime import datetime

import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup

from aries.exceptions import DocumentLoadError
from aries.rag.loaders.base import BaseLoader, Document


class EPUBLoader(BaseLoader):
    """Load EPUB files."""

    extensions = [".epub"]

    async def load(self, path: Path) -> list[Document]:
        try:
            book = epub.read_epub(str(path))
        except Exception as exc:
            raise DocumentLoadError(f"Failed to open EPUB: {path}") from exc

        documents: list[Document] = []
        for idx, item in enumerate(book.get_items_of_type(ebooklib.ITEM_DOCUMENT)):  # type: ignore[name-defined]
            soup = BeautifulSoup(item.get_body_content(), "html.parser")
            text = soup.get_text(separator="\n")
            documents.append(
                Document(
                    content=text,
                    source=f"{path}#item={idx}",
                    metadata={
                        "name": path.name,
                        "item_index": idx,
                        "source_path": str(path),
                        "content_type": "application/epub+zip",
                        "last_modified": datetime.utcfromtimestamp(path.stat().st_mtime).isoformat()
                        + "Z",
                    },
                )
            )
        if not documents:
            raise DocumentLoadError(f"No text content found in EPUB: {path}")
        return documents
