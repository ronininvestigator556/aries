"""
Markdown loader for RAG.
"""

from pathlib import Path
from datetime import datetime

from aries.exceptions import DocumentLoadError
from aries.rag.loaders.base import BaseLoader, Document


class MarkdownLoader(BaseLoader):
    """Load Markdown files as plain text."""

    extensions = [".md", ".markdown"]

    async def load(self, path: Path) -> list[Document]:
        try:
            content = path.read_text(encoding="utf-8")
        except Exception as exc:
            raise DocumentLoadError(f"Failed to read {path}") from exc

        return [
            Document(
                content=content,
                source=str(path),
                metadata={
                    "name": path.name,
                    "source_path": str(path),
                    "content_type": "text/markdown",
                    "last_modified": datetime.utcfromtimestamp(path.stat().st_mtime).isoformat()
                    + "Z",
                },
            )
        ]
