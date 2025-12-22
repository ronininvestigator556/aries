# ARIES - Local-First, Terminal-Native AI Workbench

## Project Overview

Aries is a **local-first, terminal-native AI workbench** that connects to locally running LLMs via Ollama. It includes RAG, web search (SearXNG), file system tools, and audited shell access. Aries is **domain-neutral** by design and focuses on research, synthesis, and tool-augmented reasoning with inspectable behavior.

**Target User:** Local-first operators who need transparent, policy-driven tooling for research and synthesis (no embedded domain semantics).

**Platform:** Cross-platform terminal experience with no cloud dependency in core.

## Core Design Principles

1. **Local-First:** Core works offline; networked tools are explicit opt-ins.
2. **Terminal-First:** All interaction happens in the terminal with Rich + prompt-toolkit.
3. **Inspectable:** Context injection, RAG citations, and tool executions are transparent and logged.
4. **Policy-Driven:** Capabilities are governed by configuration (profiles, allowlists), not prompt hacks.
5. **Composable:** Extensions land via providers/tools, not core rewrites; no domain semantics in core.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Terminal Interface                       │
│                   (Textual/Rich + Prompt-Toolkit)            │
├─────────────────────────────────────────────────────────────┤
│                      Command Router                          │
│         /model  /rag  /prompt  /search  /shell  /clear      │
├──────────┬──────────┬───────────┬───────────┬───────────────┤
│  Ollama  │   RAG    │   Web     │   File    │    Shell      │
│  Client  │  Engine  │  Search   │  Tools    │   Manager     │
├──────────┴──────────┴───────────┴───────────┴───────────────┤
│                   Conversation Manager                       │
│            (Context, History, Tool Results)                  │
├─────────────────────────────────────────────────────────────┤
│                    Config / State                            │
│         (YAML config, conversation logs, RAG indices)        │
└─────────────────────────────────────────────────────────────┘
```

## Phase 2 Focus (Roadmap Alignment)

- Optional **workspaces & persistence** (transcripts, artifacts, indexes).
- **Trustworthy RAG** with deterministic ingestion and stable citation handles.
- **Tool policy & auditability**: allowlists, bounded execution, structured logs.
- **Prompt profiles** as behavior contracts.
- **Export & portability** of workspaces and artifacts.

## Tech Stack

| Component | Technology | Notes |
|-----------|------------|-------|
| Language | Python 3.11+ | Type hints required everywhere |
| CLI/TUI | `textual` + `rich` | Async-native, streaming support |
| Input | `prompt_toolkit` | Command history, completion |
| LLM Backend | Ollama (official Python client) | Local model serving |
| Embeddings | Ollama (nomic-embed-text) | Local embeddings for RAG |
| Vector Store | ChromaDB | File-based, zero config |
| Doc Loading | `unstructured`, `pypdf`, `ebooklib` | PDF, EPUB, MD, TXT |
| Web Search | SearXNG | Self-hosted, private |
| Config | YAML + Pydantic | Type-safe configuration |
| Shell | `subprocess` + `asyncio` | Async process management |

## Collaboration Model

Per `CONTRIBUTING.md`, ownership is split across collaborating agents:

- **Codex:** Implementation and wiring.
- **Claude Code:** Specs, tests, and docs.
- **Gemini:** RAG and UX ergonomics.

Keep changes aligned with the roadmap, issue templates, and inspectability requirements.

## Directory Structure

```
aries/
├── pyproject.toml              # Dependencies, project metadata
├── README.md                   # User-facing documentation
├── CLAUDE.md                   # This file - Claude Code context
├── CONVENTIONS.md              # Coding standards
├── config.yaml                 # User configuration (git-ignored in production)
├── config.example.yaml         # Example configuration (committed)
├── aries/
│   ├── __init__.py             # Package init, version
│   ├── __main__.py             # Entry point: python -m aries
│   ├── cli.py                  # Main CLI loop, command routing
│   ├── config.py               # Config loading, Pydantic models
│   ├── exceptions.py           # Custom exceptions
│   ├── commands/
│   │   ├── __init__.py         # Command registry
│   │   ├── base.py             # Base command class
│   │   ├── model.py            # /model - list/switch models
│   │   ├── rag.py              # /rag - select RAG directory
│   │   ├── prompt.py           # /prompt - switch system prompts
│   │   ├── search.py           # /search - manual web search
│   │   ├── shell.py            # /shell - spawn shell session
│   │   ├── clear.py            # /clear - reset conversation
│   │   ├── help.py             # /help - command reference
│   │   └── config_cmd.py       # /config - view/edit settings
│   ├── core/
│   │   ├── __init__.py
│   │   ├── ollama_client.py    # Ollama API wrapper
│   │   ├── conversation.py     # Message history, context window
│   │   ├── message.py          # Message dataclasses
│   │   └── streaming.py        # Streaming response handler
│   ├── rag/
│   │   ├── __init__.py
│   │   ├── indexer.py          # Index documents to ChromaDB
│   │   ├── retriever.py        # Query vector store
│   │   ├── chunker.py          # Document chunking strategies
│   │   └── loaders/
│   │       ├── __init__.py
│   │       ├── base.py         # Base loader interface
│   │       ├── pdf.py          # PDF loader
│   │       ├── epub.py         # EPUB loader
│   │       ├── markdown.py     # Markdown loader
│   │       └── text.py         # Plain text loader
│   ├── tools/
│   │   ├── __init__.py         # Tool registry
│   │   ├── base.py             # Base tool interface
│   │   ├── filesystem.py       # File read/write/list/navigate
│   │   ├── web_search.py       # SearXNG integration
│   │   ├── shell.py            # Shell command execution
│   │   └── image.py            # Image loading for vision models
│   └── ui/
│       ├── __init__.py
│       ├── app.py              # Main Textual app (if using full TUI)
│       ├── display.py          # Rich console output, streaming
│       ├── input.py            # Prompt toolkit input handling
│       └── themes.py           # Color schemes
├── prompts/                    # Saved system prompts
│   ├── default.md              # Default system prompt
│   ├── researcher.md           # Research-focused prompt
│   └── coder.md                # Coding-focused prompt
├── indices/                    # ChromaDB indices (git-ignored)
│   └── .gitkeep
├── docs/
│   ├── SPECIFICATION.md        # Detailed feature specification
│   ├── API.md                  # Internal API documentation
│   └── TOOLS.md                # Tool documentation
└── tests/
    ├── __init__.py
    ├── conftest.py             # Pytest fixtures
    ├── test_ollama_client.py
    ├── test_conversation.py
    ├── test_rag.py
    └── test_tools.py
```


## Commands Reference

All commands start with `/` and are processed before being sent to the LLM.

| Command | Arguments | Description |
|---------|-----------|-------------|
| `/model` | `[name]` | List models or switch to specified model |
| `/model list` | - | Show all available Ollama models |
| `/model pull <name>` | `name` | Pull a new model from Ollama |
| `/rag` | `[path]` | List RAG indices or activate one |
| `/rag index <path>` | `path` | Index a directory for RAG |
| `/rag off` | - | Disable RAG for current session |
| `/prompt` | `[name]` | List prompts or switch to specified prompt |
| `/prompt show` | - | Display current system prompt |
| `/search` | `<query>` | Execute web search and display results |
| `/shell` | `[command]` | Open shell or execute command |
| `/clear` | - | Clear conversation history |
| `/config` | `[key] [value]` | View or set configuration |
| `/save` | `[filename]` | Save conversation to file |
| `/help` | `[command]` | Show help for all or specific command |
| `/exit` | - | Exit Aries |

## Tool System

Tools are capabilities the LLM can invoke during a conversation. They follow a request-execute-respond pattern.

### Available Tools

1. **read_file** - Read contents of a file
   - Input: `path` (string), `encoding` (optional)
   - Output: File contents or error
   - Supports: Text files, recognizes images for vision models

2. **write_file** - Write or append to a file
   - Input: `path`, `content`, `mode` ('write' | 'append')
   - Output: Success confirmation or error

3. **list_directory** - List directory contents
   - Input: `path`, `recursive` (bool), `pattern` (glob)
   - Output: File/folder listing with metadata

4. **search_web** - Search via SearXNG
   - Input: `query`, `num_results` (default 5)
   - Output: List of results with title, URL, snippet

5. **execute_shell** - Run shell command
   - Input: `command`, `timeout` (seconds), `cwd` (optional)
   - Output: stdout, stderr, return code

6. **read_image** - Load image for vision model analysis
   - Input: `path`
   - Output: Base64-encoded image ready for LLM

### Tool Invocation Flow

```
User Query → LLM decides tool needed → Tool call generated → 
Tool executed → Result injected into context → LLM continues response
```

## RAG System

### Indexing

Pre-index document directories using the CLI:
```bash
python -m aries index /path/to/documents --name my_research
```

Or use the `/rag index` command interactively.

### Supported Document Types

| Type | Extension | Loader | Notes |
|------|-----------|--------|-------|
| PDF | `.pdf` | pypdf | Text extraction, OCR not included |
| EPUB | `.epub` | ebooklib | Full text extraction |
| Markdown | `.md` | Native | Preserves structure |
| Text | `.txt` | Native | Direct loading |
| Prompt | `.prompt` | Native | Loaded as system context |

### Chunking Strategy

- **Markdown/Text:** Split by headers, then by paragraphs if too large
- **PDF/EPUB:** Split by pages/chapters, then by paragraphs
- **Chunk size:** ~500 tokens with 50 token overlap
- **Metadata:** Source file, page/section number preserved

### Retrieval

When RAG is active:
1. User query is embedded using the configured embedding model
2. Top-k similar chunks retrieved (default k=5)
3. Chunks injected into context before LLM generation
4. Source attribution included in response

## Configuration

Configuration is loaded from `config.yaml` with the following structure:

```yaml
# Ollama settings
ollama:
  host: "http://localhost:11434"
  default_model: "llama3.2"
  embedding_model: "nomic-embed-text"
  timeout: 120

# SearXNG settings  
search:
  searxng_url: "http://localhost:8080"
  default_results: 5
  timeout: 30

# RAG settings
rag:
  chunk_size: 500
  chunk_overlap: 50
  top_k: 5
  indices_dir: "./indices"

# UI settings
ui:
  theme: "dark"
  stream_output: true
  show_thinking: false
  max_history_display: 50

# Tool settings
tools:
  shell_timeout: 30
  max_file_size_mb: 10
  allowed_extensions: ["*"]  # or specific list

# Prompts
prompts:
  directory: "./prompts"
  default: "default"
```


## Implementation Phases

### Phase 1: Core MVP (Priority: CRITICAL)

**Goal:** Basic functional chat with Ollama, model switching, file tools.

1. **Project Setup**
   - [ ] pyproject.toml with all dependencies
   - [ ] Basic package structure
   - [ ] Config loading with Pydantic
   - [ ] Entry point working (`python -m aries`)

2. **Ollama Integration**
   - [ ] Connect to Ollama API
   - [ ] List available models
   - [ ] Send messages and receive streaming responses
   - [ ] `/model` command implementation

3. **Basic UI**
   - [ ] Rich console output with streaming
   - [ ] Prompt toolkit input with history
   - [ ] Command parsing and routing
   - [ ] `/clear`, `/exit`, `/help` commands

4. **File Tools**
   - [ ] `read_file` tool
   - [ ] `write_file` tool  
   - [ ] `list_directory` tool
   - [ ] Image loading for vision models

5. **Conversation Management**
   - [ ] Message history storage
   - [ ] Context window management
   - [ ] Tool call/response tracking

### Phase 2: RAG & Search (Priority: HIGH)

1. **RAG Indexing**
   - [ ] Document loaders (PDF, EPUB, MD, TXT)
   - [ ] Chunking implementation
   - [ ] ChromaDB integration
   - [ ] Embedding via Ollama
   - [ ] CLI indexing command

2. **RAG Retrieval**
   - [ ] Query embedding
   - [ ] Similarity search
   - [ ] Context injection
   - [ ] `/rag` command implementation

3. **Web Search**
   - [ ] SearXNG client
   - [ ] `search_web` tool
   - [ ] `/search` command
   - [ ] Result formatting

### Phase 3: Shell & Polish (Priority: MEDIUM)

1. **Shell Integration**
   - [ ] `execute_shell` tool
   - [ ] `/shell` command
   - [ ] Output capture and streaming
   - [ ] Timeout handling

2. **Prompt Management**
   - [ ] Load prompts from directory
   - [ ] `/prompt` command
   - [ ] Prompt variables/templating

3. **Quality of Life**
   - [ ] Conversation save/export
   - [ ] Better error messages
   - [ ] Input validation
   - [ ] Progress indicators

### Phase 4: Runpod & Advanced (Priority: LOW - FUTURE)

- [ ] Runpod endpoint integration
- [ ] Remote model management
- [ ] Session persistence
- [ ] Advanced TUI (panels, layouts)

### Phase 5: MCP Integration (Priority: FUTURE)

- [ ] MCP Server Compatibility
- [ ] Integration with desktop-commander
- [ ] Integration with Playwright for browser automation
- [ ] Enhanced file handling and navigation

## Development Guidelines

### When Working on This Project

1. **Always check existing code** before implementing new features
2. **Run type checking** with `pyright` or `mypy` before committing
3. **Write tests** for core functionality (tools, RAG, conversation)
4. **Use async/await** for all I/O operations
5. **Handle errors gracefully** - never let exceptions crash the app
6. **Log important operations** using structured logging

### Code Review Checklist

- [ ] Type hints on all function signatures
- [ ] Docstrings on public functions/classes
- [ ] No hardcoded values (use config)
- [ ] Error handling with informative messages
- [ ] Async where appropriate
- [ ] Tests for new functionality

## Key Files to Understand

Before making changes, understand these core files:

1. `aries/cli.py` - Main loop and command routing
2. `aries/config.py` - Configuration model and loading
3. `aries/core/ollama_client.py` - LLM communication
4. `aries/core/conversation.py` - Message history
5. `aries/tools/base.py` - Tool interface

## Common Tasks

### Adding a New Command

1. Create `aries/commands/mycommand.py`
2. Inherit from `BaseCommand`
3. Implement `execute()` method
4. Register in `aries/commands/__init__.py`

### Adding a New Tool

1. Create function in appropriate `aries/tools/*.py`
2. Inherit from `BaseTool`
3. Define `name`, `description`, `parameters` schema
4. Implement `execute()` method
5. Register in `aries/tools/__init__.py`

### Adding a New Document Loader

1. Create `aries/rag/loaders/myformat.py`
2. Inherit from `BaseLoader`
3. Implement `load()` method returning `List[Document]`
4. Register in `aries/rag/loaders/__init__.py`
