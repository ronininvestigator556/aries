"""
Base document loader interface.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Document:
    """A loaded document with metadata."""
    
    content: str
    source: str
    metadata: dict[str, Any] = field(default_factory=dict)
    
    @property
    def page_count(self) -> int | None:
        """Get page count if available."""
        return self.metadata.get("page_count")


class BaseLoader(ABC):
    """Abstract base class for document loaders."""
    
    # File extensions this loader handles
    extensions: list[str] = []
    
    @abstractmethod
    async def load(self, path: Path) -> list[Document]:
        """Load document(s) from a file.
        
        Args:
            path: Path to the file.
            
        Returns:
            List of Document objects.
            
        Raises:
            DocumentLoadError: If loading fails.
        """
        pass
    
    def can_load(self, path: Path) -> bool:
        """Check if this loader can handle the file.
        
        Args:
            path: Path to check.
            
        Returns:
            True if this loader handles the file type.
        """
        return path.suffix.lower() in self.extensions
