# Contributing to Aries

Thank you for contributing to Aries.

This document defines the **architectural contract** all contributions must follow.

---

## What Aries Is

Aries is a **local-first, terminal-native AI workbench** designed for:

- Research
- Synthesis
- Tool-augmented reasoning
- Knowledge exploration

It is **not** a domain-specific application.

---

## Core Architectural Concepts

### Session
- A live REPL interaction
- Ephemeral by default

### Workspace
- Optional persistence container
- Stores transcripts, artifacts, and indexes
- No domain semantics

### Artifact
- Any generated output
- Must be registered with metadata

### Index (RAG)
- Named knowledge base
- Deterministic ingestion
- Inspectable retrieval

### Tool
- A capability, not an action
- Governed by policy
- Always logged

---

## Non-Negotiable Rules

### 1. Inspectability
- RAG injections must be traceable via citation handles
- Tool calls must be logged with timestamps and hashes

### 2. Policy Enforcement
- Tool permissions are enforced in code, not by prompts
- Profiles must not bypass tool policy

### 3. Determinism (Where Feasible)
- Same input → same ingestion → same chunks
- Retrieval changes must be measurable

### 4. No Domain Assumptions
🚫 Do not introduce:
- “Cases”
- “Subjects”
- “Investigations”
- Any domain-specific language

These belong in downstream projects, not Aries Core.

---

## Tooling Expectations

### Transcripts
- Format: NDJSON
- Event types:
  - `user_message`
  - `assistant_message`
  - `tool_call`
  - `tool_result`
  - `system_event`

### Tool Logs
- Structured JSON
- Sanitized arguments
- Output size capped
- Hashes preferred over raw blobs

### Artifacts
- Must be registered in an artifact manifest
- Include: id, type, source, timestamp, hash

---

## RAG Requirements

- All chunks must have:
  - Source path
  - Section or page reference
  - Chunk ID
  - Hash
- Retrieval must surface citation handles
- `/rag show` must display exact injected content

---

## Profiles

- Profiles are YAML-defined
- Profiles may define:
  - System prompt
  - Allowed tools
  - Output style constraints
- Profiles must not:
  - Enable forbidden tools
  - Override policy enforcement

---

## PR Guidelines

### Before Opening a PR
- Run tests
- Update documentation if behavior changes
- Ensure logs and artifacts remain inspectable

### PRs Will Be Rejected If They:
- Add hidden automation
- Execute tools silently
- Introduce domain semantics
- Break portability
- Reduce inspectability

---

## Ownership Split (Guideline)

- **Implementation / wiring** → Codex-style agents
- **Specs, tests, docs** → Claude-style agents
- **RAG + UX ergonomics** → Gemini-style agents

---

## Philosophy

Aries favors:
- Explicit over implicit
- Inspectable over magical
- Bounded over autonomous
- Composable over monolithic

If a feature makes the system harder to reason about, it probably doesn’t belong in core.
