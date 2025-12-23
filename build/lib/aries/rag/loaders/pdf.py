"""
PDF loader for RAG using pypdf.
"""

from pathlib import Path
from datetime import datetime

from pypdf import PdfReader

from aries.exceptions import DocumentLoadError
from aries.rag.loaders.base import BaseLoader, Document


class PDFLoader(BaseLoader):
    """Load PDF files."""

    extensions = [".pdf"]

    async def load(self, path: Path) -> list[Document]:
        try:
            reader = PdfReader(str(path))
        except Exception as exc:
            raise DocumentLoadError(f"Failed to open PDF: {path}") from exc

        documents: list[Document] = []
        for idx, page in enumerate(reader.pages):
            try:
                text = page.extract_text() or ""
            except Exception as exc:
                raise DocumentLoadError(f"Failed to read page {idx} in {path}") from exc
            documents.append(
                Document(
                    content=text,
                    source=f"{path}#page={idx + 1}",
                    metadata={
                        "page": idx + 1,
                        "name": path.name,
                        "source_path": str(path),
                        "content_type": "application/pdf",
                        "last_modified": datetime.utcfromtimestamp(path.stat().st_mtime).isoformat()
                        + "Z",
                    },
                )
            )
        return documents
