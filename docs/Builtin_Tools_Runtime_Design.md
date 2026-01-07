# Builtin Tools Runtime Design

## 1) Problem statement + goals

ARIES currently relies on external tool runtimes (MCP/desktop-commander/playwright) as foundational building blocks for filesystem, shell, and web interactions. This introduces additional dependencies, increases the surface area for failure, and makes deterministic testing harder. We want a built-in, rock-solid tool runtime that makes common agentic tasks “just work” from natural language while preserving the current governance model (policy evaluation, approvals, workspace boundaries, auditability).

**Goals**
- “Just works” agentic tasks with filesystem + shell + web capabilities.
- Minimal external runtime dependencies for core functionality.
- Preserve governance invariants (policy evaluation, approvals, risk tiers, allowlists).
- Maintain structured auditability and determinism suitable for testing and golden transcripts.

## 2) Non-goals

- Full browser automation is not a core requirement (Playwright can remain optional later).
- No weakening of approvals, risk gating, or workspace boundary enforcement.

## 3) Proposed architecture

### Builtin provider
Add a **Builtin** provider that exposes first-party tools and becomes the default runtime. MCP remains supported as an optional provider.

**Built-in tool set (initial)**
- Filesystem
  - `fs_list_dir`
  - `fs_read_text`
  - `fs_write_text`
  - `fs_search_text`
  - `fs_apply_patch` (or reuse existing `file_edit` semantics if already in the patch-first pipeline)
- Shell
  - `shell_start`
  - `shell_poll`
  - `shell_kill`
  - `shell_run`
- Web
  - `web_search` (SearXNG)
  - `web_fetch`
  - `web_extract` (optional HTML→text extraction)

### Tool IDs and registration
Tool ID naming convention (locked for builtin tools):
- `builtin:fs:list_dir`, `builtin:fs:read_text`, `builtin:fs:write_text`, `builtin:fs:search_text`, `builtin:fs:apply_patch`.
- `builtin:shell:start`, `builtin:shell:poll`, `builtin:shell:kill`, `builtin:shell:run`.
- `builtin:web:search`, `builtin:web:fetch`, `builtin:web:extract`.

Map these to existing `ToolCallRequest` and `ToolRegistry` entries. The Builtin provider should register these tool definitions, each with structured input/output schemas and clear policy metadata.

### Result schemas and artifacts
All tool results should follow a JSON-like, deterministic structure:
- `status`: `ok` | `error`
- `data`: tool-specific payload
- `error`: `{ type, message, retryable?, details? }`
- `meta`: timing, byte counts, truncation flags, workspace path normalization details

Artifacts (e.g., web fetch bodies, file content snapshots, diff hunks) should be recorded in the structured audit trail and stored in the same artifact system used today. The /policy explain-last path should include built-in tool invocations exactly like MCP ones.

## 4) Policy & governance mapping

All built-in tool calls **must** route through `execute_tool_call_with_policy()`.

### Default risk tiers
- Filesystem
  - `fs_list_dir`: `READ_ONLY`
  - `fs_read_text`: `READ_ONLY`
  - `fs_search_text`: `READ_ONLY`
  - `fs_write_text`: `WRITE_DESTRUCTIVE` (or `WRITE_SAFE` if available) based on current tier definitions
  - `fs_apply_patch`: `WRITE_DESTRUCTIVE`
- Shell
  - `shell_start`: `EXEC_USERSPACE`
  - `shell_poll`: `READ_ONLY`
  - `shell_kill`: `EXEC_USERSPACE`
  - `shell_run`: `EXEC_USERSPACE`
- Web
  - `web_search`: `NETWORK`
  - `web_fetch`: `NETWORK`
  - `web_extract`: `READ_ONLY`

### Approval rules (guide/commander/strict)
Document explicit approval requirements by tool:
- **guide**: allow READ_ONLY without explicit approval; require approval for EXEC_* / NETWORK / WRITE_* tiers.
- **commander**: allow READ_ONLY and allowlisted EXEC_USERSPACE auto-execute. NETWORK / WRITE_DESTRUCTIVE / EXEC_PRIVILEGED require approval unless explicitly allowlisted.
- **strict**: all non-READ_ONLY operations require approval.

### Workspace/path validation requirements
- **Allowed roots vs workspace boundary:** path parameters must satisfy `allowed_roots` (configured allowlist) and must not escape via symlinks. Artifacts are always stored within the workspace boundary, regardless of path inputs.
- All filesystem tools must:
  - Enforce `allowed_roots` and disallow symlink escapes.
  - Resolve real paths and re-check policy after normalization.
  - Reject traversal outside workspace boundaries with typed errors.

- Shell tools must:
  - Execute within workspace boundary (default `cwd` inside allowed roots).
  - Resolve binaries according to allowlists if existing policy requires it.

- Web tools must:
  - Respect allowlist/denylist policies (domains/URLs) if already defined.

## 5) Determinism & reliability design

### Deterministic ordering
- Directory listings and search results must be stable and sorted (lexicographic by normalized path).

### Size limits and truncation
- Define per-tool max byte limits (configurable):
  - `fs_read_text`: max bytes, return truncated data with `truncated=true`.
  - `fs_search_text`: limit matches + per-match context size.
  - `web_fetch`: max bytes with truncation metadata.
- Tool responses should include `meta.truncated` and `meta.bytes_read`.

### Error handling
- Typed error structure:
  - `type`: `NotFound`, `PermissionDenied`, `InvalidInput`, `PolicyDenied`, `Timeout`, `TooLarge`, `InternalError`.
  - `retryable`: boolean for automated retries.

### Process management (Windows + Linux)
- `shell_start` returns a stable `process_id`.
- `shell_poll` returns exit status, stdout/stderr tail, and `running` flag.
- Use backoff for polling and include stall detection metadata (no output for N seconds).
- `shell_kill` supports graceful then forceful termination with platform-specific handling.

### Web fetching
- Timeouts: connect + read (configurable).
- Redirect policy: maximum redirects and disallow scheme changes if policy requires.
- Content-type handling: store raw bytes and optionally text extraction in `web_extract`.
- `web_extract(artifact_id)` is READ_ONLY; `web_fetch(url)` is NETWORK. `web_extract(url)` should be disallowed or treated as NETWORK.
- HTML→text extraction should be deterministic (strip scripts/styles, normalize whitespace).
- Store fetched content as artifacts and return references for citation tracking.

## 6) Migration plan

### Phase 0: Spec
- Finalize tool schemas, risk tiers, and policy mapping.
- Document provider interfaces and registration.

### Phase 1: Filesystem built-ins (minimal change set)
- Implement `fs_list_dir`, `fs_read_text`, `fs_write_text`, `fs_search_text`, `fs_apply_patch`.
- Register tools via Builtin provider, use existing policy gateway.

### Phase 2: Shell built-ins
- Implement `shell_start`, `shell_poll`, `shell_kill`, `shell_run`.
- Add subprocess and polling implementation with deterministic output handling.

### Phase 3: Web built-ins
- Implement `web_search` (SearXNG), `web_fetch`, `web_extract`.
- Add artifact storage for citations and HTML→text extraction.

### Phase 4: MCP demotion
- Keep MCP provider supported but disabled by default.
- Provide configuration flags:
  - `providers.builtin.enabled=true`
  - `providers.mcp.enabled=false` by default

### Minimal churn strategy
- Prefer new modules and focused integration points.
- Avoid large refactors; add provider registration without changing unrelated components.

### Optional: /doctor command
- Provide a capability check to confirm builtin tools are available and policy evaluation works.

## 7) Acceptance criteria (testable)

- ARIES runs with `providers.mcp.enabled=false` and Desktop Ops still works via builtin tools.
- `/desktop` create file + list dir works in Windows allowed_roots.
- `/desktop run pytest` works via shell tools.
- `web_search` + `web_fetch` returns citations stored as artifacts.
- Governance invariants remain passing and extended to builtin tools.

## 8) Test strategy

- Add unit tests for builtin tools.
- Update governance invariant tests to assert builtin tools route through the policy gateway.
- Add golden transcripts for:
  - list directory
  - create file
  - start process + poll
  - web search + fetch
- Ensure no “empty plan” silent failures when tools exist: if a supported intent and tool exist, Desktop Ops must emit at least one step or raise a clear error.
