# Aries — AI Research & Investigation Enhancement System

Aries is a terminal-first AI assistant that connects to locally running LLMs via **Ollama**. It ships with command-driven controls, streaming console output, and tool integrations for files, shell commands, and basic vision image loading. The project prioritizes local-first workflows for research and investigation tasks without relying on cloud services.

## Current state (Phase 1)

The codebase implements the core Minimum Viable Product:

- **CLI app**: `python -m aries` starts the Rich-powered console loop with prompt-toolkit input and command routing.
- **Ollama integration**: Lists models, switches active models, and streams chat responses.
- **Commands**: `/model`, `/help`, `/clear`, `/exit` are available; additional commands from later phases (e.g., RAG/search) are not yet implemented.
- **Conversation management**: Tracks history, tool calls/results, and prunes context by message count and token budget.
- **Tools**: File read/write/list, shell execution, and image loading for vision models are registered for model tool-calling.
- **Configuration**: YAML-backed config with defaults for Ollama, UI, tools, prompts, and conversation limits.
- **Tests**: Automated coverage for configuration, conversation behavior, Ollama client stubs, and all Phase 1 tools (`pytest`).

### Not yet implemented (future phases)

- RAG indexing/retrieval, web search, and advanced TUI layout.
- Additional commands (`/rag`, `/search`, `/prompt`, etc.) and full tool/result rendering beyond the basics.
- Robust prompt library management and persistence for conversation logs.

## Quick start

1. **Install dependencies**
   ```bash
   pip install -e .
   ```

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
