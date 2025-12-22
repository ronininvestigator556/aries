# Aries Coding Conventions

These conventions support the architectural contract in `CONTRIBUTING.md` (inspectability, policy enforcement, determinism, domain-neutrality) and the product principles in `ROADMAP.md`. Keep contributions local-first, auditable, and composable.

## Python Style

### Formatting

- **Formatter:** Black with default settings (line length 88)
- **Import sorting:** isort with Black profile
- **Linting:** Ruff for fast linting

```bash
# Format code
black aries/ tests/
isort aries/ tests/

# Lint
ruff check aries/ tests/
```

### Type Hints

**Required on all function signatures.** Use modern Python 3.11+ syntax.

```python
# Good
def process_message(content: str, role: str = "user") -> Message:
    ...

async def stream_response(prompt: str) -> AsyncIterator[str]:
    ...

def get_config() -> Config:
    ...

# Bad - missing types
def process_message(content, role="user"):
    ...
```

### Type Imports

```python
from typing import Any, AsyncIterator, Callable, TypeVar
from collections.abc import Sequence, Mapping
from pathlib import Path
```

### Optional and Union

```python
# Python 3.10+ syntax preferred
def find_file(name: str) -> Path | None:
    ...

def process(data: str | bytes) -> str:
    ...
```

## Docstrings

Use Google-style docstrings on all public functions and classes.

```python
def search_documents(
    query: str,
    top_k: int = 5,
    threshold: float = 0.7,
) -> list[Document]:
    """Search indexed documents for relevant chunks.

    Args:
        query: The search query text.
        top_k: Maximum number of results to return.
        threshold: Minimum similarity score (0-1).

    Returns:
        List of Document objects sorted by relevance.

    Raises:
        IndexNotFoundError: If no RAG index is active.
        EmbeddingError: If query embedding fails.
    """
    ...
```


## Async Patterns

### Use Async for All I/O

```python
# Good - async for I/O
async def read_file(path: Path) -> str:
    async with aiofiles.open(path) as f:
        return await f.read()

async def call_ollama(prompt: str) -> AsyncIterator[str]:
    async for chunk in client.chat_stream(prompt):
        yield chunk

# Bad - blocking I/O in async context
async def read_file(path: Path) -> str:
    with open(path) as f:  # BLOCKING!
        return f.read()
```

### Async Context Managers

```python
class OllamaClient:
    async def __aenter__(self) -> "OllamaClient":
        await self.connect()
        return self
    
    async def __aexit__(self, *args) -> None:
        await self.disconnect()

# Usage
async with OllamaClient() as client:
    response = await client.chat(prompt)
```

### Gathering Concurrent Tasks

```python
# Good - concurrent execution
async def search_multiple(queries: list[str]) -> list[Result]:
    tasks = [search_web(q) for q in queries]
    return await asyncio.gather(*tasks)

# Bad - sequential execution
async def search_multiple(queries: list[str]) -> list[Result]:
    results = []
    for q in queries:
        results.append(await search_web(q))  # SLOW!
    return results
```

## Error Handling

### Custom Exceptions

Define in `aries/exceptions.py`:

```python
class AriesError(Exception):
    """Base exception for Aries."""
    pass

class ConfigError(AriesError):
    """Configuration-related errors."""
    pass

class OllamaError(AriesError):
    """Ollama communication errors."""
    pass

class ToolError(AriesError):
    """Tool execution errors."""
    pass

class RAGError(AriesError):
    """RAG-related errors."""
    pass
```

### Error Handling Pattern

```python
# Good - specific handling with context
async def execute_tool(name: str, params: dict) -> ToolResult:
    try:
        tool = get_tool(name)
        return await tool.execute(**params)
    except FileNotFoundError as e:
        raise ToolError(f"File not found: {e.filename}") from e
    except PermissionError as e:
        raise ToolError(f"Permission denied: {e.filename}") from e
    except Exception as e:
        logger.exception(f"Unexpected error in tool {name}")
        raise ToolError(f"Tool {name} failed: {e}") from e

# Bad - silent failure or generic handling
async def execute_tool(name: str, params: dict) -> ToolResult | None:
    try:
        return await get_tool(name).execute(**params)
    except:  # NEVER DO THIS
        return None
```

### Never Crash the App

```python
# In main CLI loop
async def main_loop():
    while True:
        try:
            user_input = await get_input()
            await process_input(user_input)
        except KeyboardInterrupt:
            break
        except AriesError as e:
            display_error(str(e))
        except Exception as e:
            logger.exception("Unexpected error")
            display_error(f"Unexpected error: {e}")
```

## Logging

### Setup

```python
import logging
from rich.logging import RichHandler

logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    handlers=[RichHandler(rich_tracebacks=True)]
)

logger = logging.getLogger("aries")
```

### Usage

```python
# Good - structured, informative
logger.info("Loading model", extra={"model": model_name})
logger.debug("Tool execution", extra={"tool": name, "params": params})
logger.error("Failed to connect", extra={"host": host, "error": str(e)})

# Bad - vague, unhelpful
logger.info("doing something")
logger.error("it broke")
```


## Configuration

### Pydantic Models

```python
from pydantic import BaseModel, Field
from pathlib import Path

class OllamaConfig(BaseModel):
    host: str = "http://localhost:11434"
    default_model: str = "llama3.2"
    embedding_model: str = "nomic-embed-text"
    timeout: int = Field(default=120, ge=1)

class Config(BaseModel):
    ollama: OllamaConfig = OllamaConfig()
    # ... other sections

    @classmethod
    def load(cls, path: Path) -> "Config":
        with open(path) as f:
            data = yaml.safe_load(f)
        return cls.model_validate(data)
```

### Accessing Config

```python
# Good - pass config explicitly
async def chat(client: OllamaClient, config: Config, prompt: str):
    model = config.ollama.default_model
    ...

# Acceptable - module-level singleton for convenience
from aries.config import get_config

async def chat(client: OllamaClient, prompt: str):
    config = get_config()
    model = config.ollama.default_model
```

### No Magic Values

```python
# Good
chunk_size = config.rag.chunk_size

# Bad
chunk_size = 500  # Where does this come from?
```

## Project Structure Conventions

### One Class/Function Per Concern

```python
# Good - single responsibility
# aries/tools/filesystem.py
class ReadFileTool(BaseTool): ...
class WriteFileTool(BaseTool): ...
class ListDirectoryTool(BaseTool): ...

# Bad - god class
class FileSystemTool(BaseTool):
    def read(self): ...
    def write(self): ...
    def list(self): ...
    def delete(self): ...
```

### Imports

```python
# Standard library
import asyncio
from pathlib import Path

# Third party
from rich.console import Console
from pydantic import BaseModel

# Local
from aries.config import Config
from aries.core.ollama_client import OllamaClient
```

## Testing

### Test Structure

```
tests/
├── conftest.py          # Shared fixtures
├── test_ollama_client.py
├── test_conversation.py
├── test_tools/
│   ├── test_filesystem.py
│   └── test_web_search.py
└── test_rag/
    ├── test_indexer.py
    └── test_retriever.py
```

### Fixtures

```python
# conftest.py
import pytest
from aries.config import Config

@pytest.fixture
def config() -> Config:
    return Config()

@pytest.fixture
def temp_dir(tmp_path) -> Path:
    return tmp_path

@pytest.fixture
async def ollama_client(config):
    client = OllamaClient(config.ollama)
    yield client
    await client.close()
```

### Async Tests

```python
import pytest

@pytest.mark.asyncio
async def test_ollama_chat(ollama_client):
    response = await ollama_client.chat("Hello")
    assert response is not None
```

### Mocking

```python
from unittest.mock import AsyncMock, patch

@pytest.mark.asyncio
async def test_search_with_mock():
    with patch("aries.tools.web_search.searxng_client") as mock:
        mock.search = AsyncMock(return_value=[{"title": "Test"}])
        result = await search_web("test query")
        assert len(result) == 1
```

## Git Conventions

### Branch Names

- `feature/model-switching`
- `fix/streaming-bug`
- `refactor/tool-system`

### Commit Messages

```
feat: add /rag command for index selection
fix: handle empty response from Ollama
refactor: extract tool registry to separate module
docs: update README with installation instructions
test: add tests for conversation manager
```

## Dependencies

### Adding Dependencies

1. Add to `pyproject.toml` under `[project.dependencies]`
2. Use version constraints: `"requests>=2.28,<3.0"`
3. Run `pip install -e .` to update

### Dev Dependencies

```toml
[project.optional-dependencies]
dev = [
    "pytest>=7.0",
    "pytest-asyncio>=0.21",
    "black>=23.0",
    "ruff>=0.1",
    "pyright>=1.1",
]
```
