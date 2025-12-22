# Aries Roadmap

Aries is a **local-first, terminal-native AI workbench** for research, synthesis, and tool-augmented reasoning.

This roadmap defines *what* we are building, *why*, and *what we are explicitly not building* in the core project.

---

## Product Principles

- **Local-first**: Aries must work offline except where tools explicitly require network access.
- **Inspectable**: Context injection, retrieval, and tool usage must be visible to the operator.
- **Policy-driven**: Behavior is controlled by configuration and profiles, not prompt hacks.
- **Domain-neutral**: No domain semantics (e.g., cases, investigations) in core.
- **Composable**: Extensions are added via providers, not core rewrites.

---

## Phase 2 — Reliable Workbench (Current Focus)

**Goal:** Make Aries predictable, auditable, and reusable across sessions and workflows.

### Outcomes
- Optional persistence via workspaces
- Trustworthy, inspectable RAG
- Bounded, logged tool execution
- Prompt profiles as behavior contracts
- Portable outputs

---

### Phase 2.1 — Workspaces & Persistence

**Summary:** Introduce optional persistence without imposing domain semantics.

- Named workspaces (`aries workspace new|open|list|close`)
- Workspace-local transcripts, artifacts, and indexes
- NDJSON transcripts with tool-call events
- Artifact registry with metadata and hashes

**Done when:**
- Aries can be used ephemerally or persistently by choice
- A workspace can be exported/imported and replayed

---

### Phase 2.2 — RAG as Knowledge Substrate

**Summary:** Retrieval is explicit, testable, and explainable.

- Named indexes (`/rag index add|list|use`)
- Deterministic ingestion + chunking
- Per-chunk metadata (source, section, page, hash)
- Stable citation handles
- `/rag show` and `/rag last`
- Retrieval quality evaluation harness

**Done when:**
- Every injected chunk is inspectable
- Retrieval regressions are detectable in CI

---

### Phase 2.3 — Tool Policy, Safety, and Audit

**Summary:** Tools are capabilities governed by policy, not prompts.

- Tool enable/disable by class
- Filesystem allowlists
- Shell gating + confirmation modes
- Structured tool execution logs

**Done when:**
- Disallowed tools cannot be executed
- Every tool invocation is auditable

---

### Phase 2.4 — Prompt Profiles

**Summary:** Behavior is driven by profiles, not ad-hoc prompting.

- YAML-defined profiles
- `/profile list|use|show`
- Tool policy binding per profile
- Optional output schemas

**Done when:**
- Profiles materially change behavior without code changes

---

### Phase 2.5 — Export & Portability

**Summary:** Outputs are easy to move and archive.

- Workspace export/import
- Artifact bundle export with manifest

**Done when:**
- A workspace can be transferred and reopened elsewhere

---

## Phase 3 — Extensible Platform

**Goal:** Add extensibility and orchestration without sacrificing control or inspectability.

---

### Phase 3.1 — Provider Layer (MCP + Adapters)

- Provider interface and registry
- MCP server integration
- Tool provenance tracking

---

### Phase 3.2 — Bounded Planner

- Explicit Plan object
- `/plan propose|run|step`
- Hard limits on tool calls
- Mandatory summaries

---

### Phase 3.3 — TUI Productivity Upgrade

- Multi-pane layout
- Citation and artifact previews
- Keyboard-first navigation

---

## Explicit Non-Goals

- Autonomous agents without operator control
- Silent tool execution
- Silent context injection
- Domain-specific semantics in core
- Cloud dependency by default

---

## Future Directions (Out of Scope for Core)

- Opinionated vertical builds (e.g., investigative, academic, coding-focused)
- GUI frontends
- SaaS deployment

These may exist as **separate layers on top of Aries Core**.
