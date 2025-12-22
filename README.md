# Aries — Local-First, Terminal-Native AI Workbench

Aries is a **local-first, terminal-native AI workbench** that connects to locally running LLMs via **Ollama**. It is built for **research, synthesis, and tool-augmented reasoning** while staying domain-neutral. All core behavior prioritizes:

- **Local-first** operation with explicit opt-ins for networked tools.
- **Inspectability** of context, retrieval, and tool execution.
- **Policy-driven** capabilities rather than prompt tricks.
- **Composable** extensions through providers and tooling.

This project is a cross-collaboration between **Codex (implementation/wiring)**, **Claude Code (specs/tests/docs)**, and **Gemini (RAG + UX ergonomics)** to keep the roadmap, contributions, and tooling aligned.

## Current focus (Phase 2 — Reliable Workbench)

We are implementing the outcomes defined in `ROADMAP.md`:

- **Workspaces & persistence**: Optional, operator-controlled transcripts, artifacts, and indexes.
- **Trustworthy RAG**: Deterministic ingestion, inspectable citations, and retrieval quality checks.
- **Tool policy & auditability**: Explicit allowlists, logging, and bounded execution.
- **Prompt profiles**: YAML-defined profiles that bind tool policy and behavior.
- **Export & portability**: Workspace and artifact export/import with manifests.

Core capabilities already in the codebase include:

- **CLI app**: `python -m aries` launches the Rich-powered console loop with prompt-toolkit input and command routing.
- **Ollama integration**: Lists models, switches active models, and streams chat responses.
- **Commands**: `/model`, `/help`, `/clear`, `/exit`, `/rag` (index/select/inspect), `/workspace` (new/open/list/export/import), `/profile` (list/use/show), and `/search` (SearXNG web search).
- **Conversation management**: Tracks history, tool calls/results, and prunes context by message count and token budget.
- **Tools**: File read/write/list, shell execution, image loading for vision models, and SearXNG web search with audit-friendly logging expectations.
- **Configuration**: YAML-backed config with defaults for Ollama, UI, tools, prompts, and conversation limits.
- **RAG (early)**: Text/Markdown/PDF/EPUB loaders, token-aware chunking, ChromaDB indexing, Ollama embeddings, `/rag` command to index/select, and automatic context injection when an index is active.
- **Tests**: Automated coverage for configuration, conversation behavior, Ollama client stubs, tools, chunker, and RAG indexing/retrieval (`pytest`).

### Not yet implemented (future phases)

- Advanced TUI layout and richer prompt management UX.
- Additional RAG features (multi-format chunking strategies, better metadata, scoring).
- Further web search/result formatting and multi-tool orchestration.
- MCP (Model Context Protocol) provider layer and bounded planner per the roadmap.

## Quick start

1. **Install dependencies**
   ```bash
   pip install -e .
   ```
   > If you see `ModuleNotFoundError` (e.g., for `aiofiles`), ensure you ran the install step from your project root.

2. **Configure Ollama**
   - Ensure `ollama serve` is running locally.
   - Update `config.yaml` (or copy `config.example.yaml`) with your Ollama host and default model.

3. **(Optional) Setup Search**
   - Aries uses SearXNG for web search. You can run it easily with Docker:
     ```bash
     docker run -d -p 8080:8080 --name searxng searxng/searxng
     ```

4. **Run Aries**
   ```bash
   python -m aries
   ```

5. **Use commands**
   - `/model list` — show available models.
   - `/model <name>` — switch models.
   - `/workspace new <name>` — create a persistent workspace with transcripts and artifacts.
   - `/profile list` / `/profile use <name>` — view or apply YAML-defined behavior profiles.
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
- `tools`: shell timeout, max file size, allowed extensions, path allow/deny lists, and network/shell enablement.
- `workspace`: persistence root, default workspace, and directory names for transcripts/artifacts/indexes.
- `profiles`: profile directory and default profile name.
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

Aries follows the architectural contract in `CONTRIBUTING.md` (inspectability, policy enforcement, determinism, domain-neutrality). Coding standards live in `CONVENTIONS.md` (Black + isort, type hints everywhere, Google-style docstrings). New commands and tools should be registered through their respective registries and include accompanying tests where possible.

For planning work, align with the **feature** and **bug** issue templates in `.github/ISSUE_TEMPLATE/` so acceptance criteria, non-goals, and inspectability impacts stay clear.
