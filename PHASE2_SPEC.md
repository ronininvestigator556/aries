# Aries Phase 2 Specification — Reliable Workbench

This document expands the Phase 2 roadmap into actionable requirements and acceptance criteria. It is organized by the Phase 2 outcomes in `ROADMAP.md` and is scoped to Aries Core (no domain semantics or non-local defaults).

---

## Product principles (must remain true across all features)

- **Local-first by default:** All capabilities operate without network access unless a tool explicitly needs it and the operator opts in.
- **Inspectable:** Context injection, retrieval decisions, and tool execution must be visible and reviewable after the fact.
- **Policy-driven, not prompt-driven:** Behavior is controlled by configuration/profiles, not hidden prompt magic.
- **Domain-neutral:** No baked-in case/investigation semantics. Only generic workbench concepts (workspaces, artifacts, commands, profiles).
- **Composable:** Extension points are provided via providers/tools, not forked core implementations.

---

## Scope of Phase 2

**Goal:** Make Aries predictable, auditable, and reusable across sessions and workflows.

**Outcomes:**

1. Optional persistence via workspaces
2. Trustworthy, inspectable RAG
3. Bounded, logged tool execution
4. Prompt profiles as behavior contracts
5. Portable outputs

Out-of-scope items remain in the roadmap’s non-goals (autonomous agents, silent tool execution/context injection, domain semantics, cloud dependencies by default).

---

## Phase 2.1 — Workspaces & Persistence

**Objective:** Introduce optional persistence without forcing domain concepts.

**Functional requirements**
- CLI supports `aries workspace new|open|list|close` to manage named workspaces.
- Workspaces can be omitted; Aries must still run ephemerally with no persistence.
- Each workspace has an isolated root containing:
  - `transcripts/` with NDJSON transcripts (see schema below).
  - `artifacts/` plus an artifact registry (manifest with metadata + hashes).
  - `indexes/` holding any RAG indexes tied to that workspace.
- Switching workspaces updates the active transcript, artifact registry, and index selection.
- Workspace operations must be idempotent and safe to run repeatedly (no corruption on re-open).

**Transcript format (NDJSON)**
- Each line is a JSON object containing at least: `timestamp`, `role` (user/assistant/tool/system), `content`, `conversation_id`, and a stable `message_id`.
- Tool calls/responses include structured payloads: `tool_name`, `input`, `output`, `status` (success/fail), and `duration_ms`.
- Log entries must preserve ordering and support replay without extra context.

**Artifact registry**
- Stores per-artifact metadata: `path`, `created_at`, `mime_type`, `size_bytes`, `hash` (SHA-256), optional `description`, and the originating command/tool (for provenance).
- Registry updates must be atomic (no partial writes on failure) and deduplicate identical hashes.

**Done when**
- Aries can be run with or without workspace persistence by operator choice.
- A workspace (transcript + artifacts + indexes) can be exported/imported and replayed without manual edits.

---

## Phase 2.2 — RAG as Knowledge Substrate

**Objective:** Retrieval is explicit, deterministic, and explainable.

**Functional requirements**
- Index lifecycle commands: `/rag index add <path> [--name <id>]`, `/rag index list`, `/rag index use <id>`, `/rag index drop <id>`.
- Deterministic ingestion and chunking: same input yields identical chunk boundaries, metadata, and hashes given the same configuration.
- Supported loaders: PDF, EPUB, Markdown, Text. Loader metadata must capture `source_path`, `content_type`, `last_modified`, `page/section` where applicable.
- Chunk metadata must include: `chunk_id`, `source_path`, `section/page`, `start/end_offset`, `hash`, and `embedding_model`.
- Citation handles are stable (e.g., `<index>:<chunk_id>`); they surface in responses and map directly to chunk metadata.
- Inspection commands: `/rag show <handle>` for a specific chunk and `/rag last` for the last injected context set.
- Retrieval emits an audit log entry that records query text, active index, embedding model, search parameters (k/top_n, thresholds), and the list of returned handles with scores.
- Retrieval quality harness: deterministic dataset-based test entry point (CLI or pytest target) that reports precision/recall (or similar) and fails CI on regression.

**Done when**
- Every injected chunk is inspectable with metadata and source linkage.
- Retrieval regressions are detectable via the evaluation harness in CI.

---

## Phase 2.3 — Tool Policy, Safety, and Audit

**Objective:** Tools are capabilities governed by explicit policy.

**Functional requirements**
- Tool classes can be enabled/disabled (e.g., filesystem, shell, network) via config/profile.
- Filesystem tools respect allowlists/denylists for paths and extensions; shell commands can require confirmation or be entirely disabled.
- All tool executions are recorded with: `timestamp`, `tool_name`, `inputs`, `result` (or error), `duration_ms`, `workspace` (if any), and policy decision (allowed/blocked/confirm).
- When a tool is disallowed, the assistant receives a structured denial response indicating the policy reason (not just a textual apology).
- Default policy must be safe: deny dangerous shells unless explicitly enabled; enforce size/time limits from config.

**Done when**
- Disallowed tools cannot be executed (enforcement precedes model/tool call dispatch).
- Every tool invocation is auditable after the fact with full context and results.

---

## Phase 2.4 — Prompt Profiles

**Objective:** Operator selects behavior via explicit profiles, not ad-hoc prompts.

**Functional requirements**
- Profiles are YAML documents defining: `name`, `description`, `system_prompt` (or prompt template reference), `tool_policy` bindings, `output_schema` (optional JSON Schema), and default command/tool settings.
- CLI commands: `/profile list` (names + descriptions), `/profile use <name>`, `/profile show <name>` (display full YAML or rendered summary).
- Active profile is visible in the UI and persisted per workspace (if in persistent mode).
- Tool policy enforcement respects the active profile; switching profiles updates allowed tools immediately.
- If an `output_schema` is defined, responses are validated (or at minimum structured) accordingly, and validation failures are surfaced to the operator.

**Done when**
- Switching profiles materially changes behavior (tools, prompting, output shaping) without code changes or manual prompt editing.

---

## Phase 2.5 — Export & Portability

**Objective:** Outputs are easy to move, archive, and replay.

**Functional requirements**
- Export commands: `aries workspace export <path>` (bundle transcript + artifact registry + artifacts + indexes) and `aries workspace import <bundle>`.
- Artifact bundle includes a manifest with: list of files, hashes, sizes, MIME types, and source workspace metadata.
- Index export/import must preserve citation handles and metadata so retrieval results remain referentially stable after transfer.
- Bundles are portable archives (e.g., `.tar.zst` or similar) that can be validated via hash/signature before import.
- Import operations are safe by default: require explicit confirmation before overwriting an existing workspace, and validate manifest hashes prior to extraction.

**Done when**
- A workspace can be transferred, validated, and reopened elsewhere with intact transcripts, artifacts, and indexes.

---

## Cross-cutting acceptance criteria

- **Inspectability:** All new commands and flows include human-readable status outputs and machine-readable logs suitable for replay/audit.
- **Determinism:** Given identical inputs and configuration, operations (chunking, indexing, retrieval scoring, exports) yield identical outputs.
- **Testing hooks:** Provide CLI targets or pytest markers for RAG evaluation, policy enforcement, and workspace import/export sanity checks.
- **Documentation:** User-facing help (`/help`, README snippets) must reflect new commands and flags introduced in Phase 2.

---

## Non-goals (for emphasis)

- No autonomous agents; the operator remains in control of tool execution and context injection.
- No silent execution or hidden context changes—everything must be logged and inspectable.
- No domain-specific constructs baked into core; workspaces are generic containers, not cases or investigations.
- No mandatory cloud dependence; remote services (e.g., SearXNG) are optional and operator-provided.

---

## Completion definition

Phase 2 is complete when all outcome-specific "Done when" criteria are satisfied, tests and evaluation harnesses detect regressions, and the system remains faithful to the product principles above under both ephemeral and persistent usage.
