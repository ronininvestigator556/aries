# Aries — AI Research & Investigation Enhancement System

Aries is a terminal-first AI assistant that connects to locally running LLMs via **Ollama**. It ships with command-driven controls, streaming console output, and tool integrations for files, shell commands, and basic vision image loading. The project prioritizes local-first workflows for research and investigation tasks without relying on cloud services.

## Current state (Phase 2 in progress)

The codebase now includes the Phase 1 MVP plus the first Phase 2 capabilities:

- **CLI app**: `python -m aries` starts the Rich-powered console loop with prompt-toolkit input and command routing.
- **Ollama integration**: Lists models, switches active models, and streams chat responses.
- **Commands**: `/model`, `/help`, `/clear`, `/exit`, plus Phase 2 `/rag` (index/select) and `/search` (SearXNG web search).
- **Conversation management**: Tracks history, tool calls/results, and prunes context by message count and token budget.
- **Tools**: File read/write/list, shell execution, image loading for vision models, and SearXNG web search are registered for model tool-calling.
- **Configuration**: YAML-backed config with defaults for Ollama, UI, tools, prompts, and conversation limits.
- **RAG (early)**: Text/Markdown/PDF/EPUB loaders, token-aware chunking, ChromaDB indexing, Ollama embeddings, `/rag` command to index/select, and automatic context injection on chat when an index is active.
- **Tests**: Automated coverage for configuration, conversation behavior, Ollama client stubs, tools, chunker, and RAG indexing/retrieval (`pytest`).

### Not yet implemented (future phases)

- Advanced TUI layout, richer prompt management, and conversation persistence.
- Additional RAG features (multi-format chunking strategies, better metadata, scoring).
- Further web search/result formatting and multi-tool orchestration.

## Quick start

1. **Install dependencies**
   ```bash
   pip install -e .
   ```
   > If you see `ModuleNotFoundError` (e.g., for `aiofiles`), ensure you ran the install step from your project root.

2. **Configure Ollama**
   - Ensure `ollama serve` is running locally.
   - Update `config.yaml` (or copy `config.example.yaml`) with your Ollama host and default model.

3. **Run Aries**
   ```bash
   python -m aries
   ```

4. **Use commands**
   - `/model list` — show available models.
   - `/model <name>` — switch models.
   - `/help` — list commands.
   - `/clear` — reset conversation history.
   - `/exit` — quit.

### Tool-calling

Models that support function/tool calls can invoke the registered tools:

- `read_file`, `write_file`, `list_directory`
- `execute_shell`
- `read_image` (returns base64 for vision models)

Tool execution results are injected back into the conversation to inform follow-up model responses.

## Configuration overview

Key sections in `config.yaml`:

- `ollama`: host, default model, embedding model, timeout.
- `ui`: streaming toggle and history display limits.
- `tools`: shell timeout, max file size, allowed extensions.
- `conversation`: max context tokens and message count for pruning.
- `prompts`: directory and default prompt name.

You can regenerate a default config snapshot via:
```bash
python - <<'PY'
from aries.config import get_default_config_yaml
print(get_default_config_yaml())
PY
```

## Testing

Run the suite:
```bash
pytest
```

The tests use local stubs for Ollama interactions and a fake token encoder for deterministic behavior.

## Contributing

Follow the conventions in `CONVENTIONS.md` (Black + isort, type hints everywhere, Google-style docstrings). New commands and tools should be registered through their respective registries and include accompanying tests where possible.
