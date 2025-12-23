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
- **Tools**: File read/write/list, shell execution, image loading for vision models, and SearXNG web search with audit-friendly logging expectations, all sourced from the built-in **core provider** (optional MCP providers plug into the same registry).
- **Configuration**: YAML-backed config with defaults for Ollama, UI, tools, prompts, and conversation limits.
- **RAG (early)**: Text/Markdown/PDF/EPUB loaders, token-aware chunking, ChromaDB indexing, Ollama embeddings, `/rag` command to index/select, and automatic context injection when an index is active.
- **Tests**: Automated coverage for configuration, conversation behavior, Ollama client stubs, tools, chunker, and RAG indexing/retrieval (`pytest`).

### Not yet implemented (future phases)

- Advanced TUI layout and richer prompt management UX.
- Additional RAG features (multi-format chunking strategies, better metadata, scoring).
- Further web search/result formatting and multi-tool orchestration.
- Bounded planner/orchestration layer for complex flows.

## Quick start

1. **Install dependencies**
   ```bash
   pip install -e .
   ```
   > If you see `ModuleNotFoundError` (e.g., for `aiofiles`), ensure you ran the install step from your project root.

2. **Configure Ollama**
   - Ensure `ollama serve` is running locally.
   - Update `config.yaml` (or copy `config.example.yaml`) with your Ollama host and default model.
   - Create a profile YAML under `profiles/` (e.g., `profiles/default.yaml`) to set the system prompt and optional tool policy. Aries will fall back to `prompts/default.md` for legacy configs, emit a single warning, and still persist transcripts/artifacts when workspaces are enabled.

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
   - `/policy show` — inspect workspace-aware policy settings (includes MCP server health).
   - `/policy explain <tool> <json_args>` — dry-run a tool policy decision (supports qualified ids like `core:write_file` or `mcp:myserver:search`).
   - `/help` — list commands.
   - `/clear` — reset conversation history.
   - `/exit` — quit.

### Tool-calling

Models that support function/tool calls can invoke the registered tools. Aries loads these tools from providers via a registry; the core provider is always present, and optional MCP providers can be configured without changing policy behavior. Tools have qualified identifiers to avoid collisions:

- Core tools: `core:<tool_name>` (e.g., `core:read_file`, `core:write_file`)
- MCP tools: `mcp:<server_id>:<tool_name>` (e.g., `mcp:myserver:search`)

Unqualified names remain supported when unique; ambiguous names will surface an error with the qualified candidates to pick from.

- `read_file`, `write_file`, `list_directory`
- `execute_shell`
- `read_image` (returns base64 for vision models)

Tool execution results are injected back into the conversation to inform follow-up model responses.
Tools declare whether they mutate state and carry a risk classification; confirmation prompts honor those attributes when `tools.confirmation_required` is true, and all tool runs—including manual commands like `/search`—are filtered through the ToolPolicy allow/deny lists. Tools that emit artifacts (e.g., `write_file`) register explicit artifact hints in `artifacts/manifest.json`; legacy `metadata.path` is honored only for tools that declare `emits_artifacts`, and missing paths are logged instead of crashing.

Policy inspection examples:
```bash
/policy show
/policy explain core:write_file {"path":"notes.txt","content":"hello"}
/policy explain mcp:myserver:search {"query":"security news"}
```
/policy show now includes an Inventory summary that reports total tools, provider/server counts, and the top metadata gaps (missing `risk_level`, `emits_artifacts`, `path_params`, or network flags). Use `/policy show --verbose` or `policy.show_verbose=true` to list all detected issues when auditing providers.

### MCP server health

MCP connectivity is tracked per server with a simple lifecycle model:

- `connected`: last connect + tool listing succeeded; `tool_count` reflects the current tools.
- `disconnected`: no successful connection yet.
- `error`: last connect/list/invoke failed; `last_error` holds a short summary.

Run `/policy show` to view the MCP Servers section (server id, transport, state, tool count, last connect, and last error summary). `/policy explain` for MCP tools also reports the server state and the latest error when not connected. If a server reports `error`, verify the endpoint/command and credentials, then retry by restarting Aries (or fix the server) — no background retries are performed. Optional startup retries can be enabled via `providers.mcp.retry`.

## Phase 2 golden path

Follow this minimal flow to exercise the hardened features:

1. Start Aries with a config that points `workspace.root` and `profiles.directory` somewhere writable.
2. Create a profile file (`profiles/default.yaml`) with a `system_prompt:` stanza, then run `/profile use default` to activate it (legacy `prompts/default.md` still works with a warning).
3. Create or open a workspace: `/workspace new demo` (indexes/artifacts/transcripts live under this root).
4. Add RAG context as needed: `/rag index add <path>` and `/rag select demo`.
5. Ask the model to run a tool (e.g., write a note); confirm mutating tool calls when prompted.
6. Inspect the transcript (`workspaces/<name>/transcripts/transcript.ndjson`) and artifact manifest (`artifacts/manifest.json`) to verify the run.

## Configuration overview

Key sections in `config.yaml`:

- `ollama`: host, default model, embedding model, timeout.
- `ui`: streaming toggle and history display limits.
- `tools`: shell timeout, max file size, allowed extensions, path allow/deny lists, `allow_shell`, `allow_network`, and `confirmation_required` for mutating tools.
- `workspace`: persistence root, default workspace, and directory names for transcripts/artifacts/indexes (artifact manifests live under `artifacts/manifest.json`).
- `profiles`: profile directory, default profile name, and `require` to disable legacy prompt fallback in production.
- `providers`: strict metadata enforcement plus optional Model Context Protocol servers. Set `providers.strict_metadata=true` (bounded by `providers.strict_metadata_max_issues`) to fail startup when provider tools omit required metadata. MCP tools appear in `/policy show`/`/policy explain` and use the same ToolPolicy and confirmation gates as built-in tools. Minimal example:
  ```yaml
  providers:
    strict_metadata: false
    strict_metadata_max_issues: 25
    mcp:
      enabled: true
      require: false
      retry:
        attempts: 0     # optional retries during startup connect/list
        backoff_seconds: 0.5
      servers:
        - id: "mcp-local"
          url: "http://localhost:9000"
          # or: command: ["python", "-m", "your_mcp_server"]
          timeout_seconds: 10
  ```
- `policy`: inventory reporting verbosity controls (`policy.show_verbose`, `policy.inventory_max_issues`, `policy.inventory_verbose_limit`).
- `tokens`: token counting mode (`approx` by default for offline safety, `tiktoken` with a warning-and-fallback, or `disabled`), plus encoding and character-per-token heuristic.
- `conversation`: max context tokens and message count for pruning.
- `prompts`: directory and default prompt name (legacy fallback; Aries will migrate `prompts.default` to `profiles.default` with a warning).

You can regenerate a default config snapshot via:
```bash
python - <<'PY'
from aries.config import get_default_config_yaml
print(get_default_config_yaml())
PY
```

### Tool metadata quality & strict mode

- Each tool should declare `risk_level` (`READ`/`WRITE`/`EXEC`), `emits_artifacts`, and network flags (`transport_requires_network` + `tool_requires_network` or `requires_network`).
- Filesystem tools—or WRITE/EXEC tools with path-like schema fields—must declare `path_params`. MCP tools with loose schemas are surfaced as warnings (unknown schemas) until clarified.
- Enable `providers.strict_metadata=true` in production to block unknown-risk tools; `/policy show --verbose` lists the exact issues to resolve. Adjust `policy.show_verbose`, `policy.inventory_max_issues`, or `policy.inventory_verbose_limit` to tune inventory reporting.

## Testing

Run the suite:
```bash
pytest
```

The tests use local stubs for Ollama interactions and exercise both approximate and fallback token counting.

## Troubleshooting

- **Profile not found:** Ensure the desired profile YAML exists under `profiles/` (e.g., `profiles/default.yaml`). If migrating from a legacy prompt, keep `prompts/<name>.md` in place; Aries will fall back once and list available profiles in the error unless `profiles.require` is set.
- **Tool denied by policy:** Check `tools.allow_shell`, `tools.allow_network`, and path allow/deny lists in your config or active profile. Mutating tools may also stop at the confirmation gate when `tools.confirmation_required` is true.
- **File missing from artifacts:** Confirm a workspace is open/persisted and that the tool returned an artifact hint or `metadata.path`. Missing or invalid paths are logged; the manifest is stored under `<workspace>/artifacts/manifest.json`.

## Contributing

Aries follows the architectural contract in `CONTRIBUTING.md` (inspectability, policy enforcement, determinism, domain-neutrality). Coding standards live in `CONVENTIONS.md` (Black + isort, type hints everywhere, Google-style docstrings). New commands and tools should be registered through their respective registries and include accompanying tests where possible.

For planning work, align with the **feature** and **bug** issue templates in `.github/ISSUE_TEMPLATE/` so acceptance criteria, non-goals, and inspectability impacts stay clear.
