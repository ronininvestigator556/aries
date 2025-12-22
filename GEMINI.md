# GEMINI - Aries Project Context & Role Definition

## 1. My Role: Aries Project Debugger & Developer

I am acting as the specialized software engineer for the **Aries** project. My primary responsibilities are:

*   **Debugging:** Investigating bugs, analyzing stack traces, and fixing issues in the CLI, RAG system, or Ollama integration.
*   **Coding:** Implementing new features (commands, tools, loaders) following strict project conventions.
*   **Testing:** ensuring code quality by running `pytest` and adhering to type-checking standards (`pyright`).

## 2. Project Overview

**Aries** is a **terminal-first, local-first AI assistant** written in Python (3.11+). It acts as a rich CLI frontend for:
*   **Ollama:** Local LLM inference.
*   **RAG:** Retrieval-Augmented Generation using ChromaDB and local embeddings.
*   **Tools:** File manipulation, shell execution, and web search (SearXNG).

## 3. Architecture & Key Components

*   **Entry Point:** `aries/__main__.py` -> `aries/cli.py` (Main loop with `prompt_toolkit` & `rich`).
*   **Core:**
    *   `aries/core/ollama_client.py`: Async wrapper for Ollama API.
    *   `aries/core/conversation.py`: Manages chat history, context pruning, and tool results.
*   **Commands:** Located in `aries/commands/`. Routed via slash commands (e.g., `/model`, `/rag`, `/search`).
*   **RAG System:**
    *   `aries/rag/indexer.py`: Loads docs -> Chunks -> Embeds -> ChromaDB.
    *   `aries/rag/retriever.py`: Vector search -> Context injection.
*   **Tools:** `aries/tools/` (Filesystem, Web Search, Shell).

## 4. Development Workflows

### Running the App
```bash
python -m aries
```

### Testing
Run the full suite (mocked Ollama/Network calls):
```bash
pytest
```

### Style & Quality Checks
**Strict adherence required:**
*   **Formatting:** `black` & `isort`
*   **Linting:** `ruff`
*   **Type Checking:** `pyright` (or strict type hints in code)

```bash
# Quick check
ruff check . && black --check .
```

## 5. Coding Conventions (Quick Ref)

*   **Async/Await:** usage is MANDATORY for all I/O (file, network, DB).
*   **Type Hints:** MANDATORY on all function signatures (`def foo(a: int) -> str:`).
*   **Docstrings:** Google-style required for all public members.
*   **Error Handling:** Use custom exceptions in `aries/exceptions.py`. Never let the app crash.

## 6. Directory Map

```text
aries/
├── aries/
│   ├── cli.py              # Main application loop
│   ├── config.py           # Pydantic configuration
│   ├── commands/           # /command implementations
│   ├── core/               # LLM & Conversation logic
│   ├── rag/                # RAG (Loader -> Chunker -> Index -> Retrieve)
│   ├── tools/              # Tool implementations (File, Search, etc.)
│   └── ui/                 # Rich/Textual display logic
├── tests/                  # Pytest suite
├── config.yaml             # User config (Ollama host, paths)
└── pyproject.toml          # Project dependencies
```
