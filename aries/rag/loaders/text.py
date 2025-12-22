"""
Plain text loader for RAG.
"""

from pathlib import Path

from aries.exceptions import DocumentLoadError
from aries.rag.loaders.base import BaseLoader, Document


class TextLoader(BaseLoader):
    """Load plain text files."""

    extensions = [".txt", ".md", ".markdown"]

    async def load(self, path: Path) -> list[Document]:
        """Load a text file into a single document."""
        try:
            content = path.read_text(encoding="utf-8")
        except Exception as exc:
            raise DocumentLoadError(f"Failed to read {path}") from exc

        return [
            Document(
                content=content,
                source=str(path),
                metadata={"name": path.name},
            )
        ]
