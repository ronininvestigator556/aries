# Phase A: Operator Console

This phase enhances the Aries CLI with better ergonomics, discoverability, and control.

## New Features

### 1. Persistent Status Header
The console now displays a status bar at the bottom (via prompt toolbar) showing:
- **WS:** Current workspace
- **Model:** Active LLM model
- **Profile:** Active profile
- **RAG:** RAG status (Index name or off)
- **Status:** Idle / Running
- **Last Action:** Summary of the last command or tool execution

### 2. Command Palette (`/palette`)
A fuzzy-searchable overlay to quickly access:
- Slash commands (e.g., `/model`, `/rag`)
- Tools (mapped to usage commands)
- Recent artifacts (mapped to `/artifact open`)

**Usage:**
Type `/palette` to open. Select an item to insert it into the prompt (press Enter to confirm execution).

### 3. Action Summaries & `/last`
Tool executions now produce a standardized, concise summary line:
`Done: tool_name → N artifacts, X.XXs`

To view full details of the last action (inputs, full output, error trace), use:
```bash
/last
```

### 4. Cancellation
- **Ctrl+C**: Safely cancels the currently running tool or model stream and returns to the prompt.
- **`/cancel`**: Resets the console state if it becomes inconsistent.

### 5. Artifact Browser (`/artifacts`)
Manage and inspect workspace artifacts.

**Commands:**
- `/artifacts list`: List recent artifacts (supports `--type`, `--contains`, `--limit`).
- `/artifacts open <id>`: Show artifact path and preview text content.

## Architecture Changes
- **Input Loop**: Now uses `asyncio.Task` for processing input, enabling cancellation via `Ctrl+C`.
- **UI**: Uses `prompt_toolkit` bottom toolbar for persistent status.
- **State**: `Aries` class now tracks `ConsoleState` (last action, running status).
