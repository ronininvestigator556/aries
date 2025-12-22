import base64
import sys
from pathlib import Path

import pytest

# Ensure project root is importable
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from aries import config as config_module  # noqa: E402
from aries.config import Config  # noqa: E402
from aries.core import conversation as conversation_module  # noqa: E402
from aries.core import ollama_client as ollama_client_module  # noqa: E402


@pytest.fixture(autouse=True)
def reset_config() -> Config:
    """Reset the global configuration before each test."""
    config = Config()
    config_module._config = config  # type: ignore[attr-defined]
    yield config
    config_module._config = None  # type: ignore[attr-defined]


@pytest.fixture(autouse=True)
def patch_tiktoken(monkeypatch: pytest.MonkeyPatch) -> None:
    """Avoid network downloads by stubbing tiktoken encoders."""

    class _FakeEncoder:
        def encode(self, text: str) -> list[int]:
            return list(text.encode("utf-8"))
        
        def decode(self, tokens: list[int]) -> str:
            return bytes(tokens).decode("utf-8")

    monkeypatch.setattr(conversation_module.tiktoken, "get_encoding", lambda _: _FakeEncoder())
    monkeypatch.setattr(
        ollama_client_module.ollama, "ResponseError", Exception
    )  # simplify tests without network


@pytest.fixture
def temp_file(tmp_path: Path) -> Path:
    """Create a temporary text file with sample content."""
    file_path = tmp_path / "sample.txt"
    file_path.write_text("hello world", encoding="utf-8")
    return file_path


@pytest.fixture
def temp_image(tmp_path: Path) -> Path:
    """Create a small temporary binary file to emulate an image."""
    file_path = tmp_path / "image.bin"
    file_path.write_bytes(base64.b64decode(base64.b64encode(b"fake image content")))
    return file_path
