import base64
import sys
import asyncio
from pathlib import Path

import pytest

# Ensure project root is importable
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from aries import config as config_module  # noqa: E402
from aries.config import Config  # noqa: E402
from aries.core import ollama_client as ollama_client_module  # noqa: E402


def pytest_configure(config: pytest.Config) -> None:
    """Register custom markers used in the test suite."""
    config.addinivalue_line("markers", "asyncio: mark test as requiring an asyncio event loop")


@pytest.hookimpl(tryfirst=True)
def pytest_pyfunc_call(pyfuncitem: pytest.Function) -> bool | None:
    """Provide lightweight asyncio support when pytest-asyncio is unavailable."""
    testfunction = pyfuncitem.obj
    if not asyncio.iscoroutinefunction(testfunction):
        return None

    if pyfuncitem.get_closest_marker("anyio"):
        # Let anyio plugin handle its own marked tests
        return None

    if not pyfuncitem.get_closest_marker("asyncio"):
        return None

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        argnames = getattr(pyfuncitem._fixtureinfo, "argnames", ())
        funcargs = {name: pyfuncitem.funcargs[name] for name in argnames}
        loop.run_until_complete(testfunction(**funcargs))
    finally:
        loop.close()
        asyncio.set_event_loop(None)
    return True


@pytest.fixture(autouse=True)
def reset_config() -> Config:
    """Reset the global configuration before each test."""
    config = Config()
    config_module._config = config  # type: ignore[attr-defined]
    yield config
    config_module._config = None  # type: ignore[attr-defined]


@pytest.fixture(autouse=True)
def patch_ollama_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    """Simplify tests without hitting the network."""

    monkeypatch.setattr(ollama_client_module.ollama, "ResponseError", Exception)


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
