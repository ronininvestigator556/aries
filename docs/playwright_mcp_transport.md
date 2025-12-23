# Playwright MCP Transport & Security

This document explains the transport architecture, security posture, and deployment recommendations for the Aries Playwright MCP (Model Context Protocol) integration.

## Transport Architecture

Aries supports two primary transport mechanisms for MCP servers: **Command (stdio-like)** and **HTTP**.

### One-Shot Command Transport
The default transport for the Playwright MCP server (`aries/providers/playwright_server/server.py`) is the **Command Transport**.

- **Mechanism**: For every tool listing or invocation, Aries executes the server script as a subprocess (e.g., `python -m aries.providers.playwright_server.server --invoke ...`).
- **Implications**: 
    - **Statelessness**: Each process is independent and terminates immediately after returning the JSON result.
    - **Isolation**: Crashes in one tool invocation do not affect subsequent calls.
    - **Performance**: High overhead due to process startup (Python interpreter + library imports).

### Stub Mode
To support testing and development without a real browser, the Playwright server includes a **Stub Mode**.

- **Activation**: Enabled by setting the environment variable `ARIES_PLAYWRIGHT_STUB=1`.
- **State Persistence**: Since the command transport is one-shot, the stub mode persists its "state" (e.g., active browser contexts and URLs) in a temporary JSON file (`aries_playwright_stub_state.json`) located in the system's temporary directory.
- **Behavior**:
    - **browser_new_context**: Generates a dummy context ID and saves it to the state file.
    - **page_screenshot**: Writes a dummy file to the requested path and returns an artifact reference.
    - **page_content**: Returns a static HTML string containing the "current" URL from the state file.

## Production Deployment: HTTP Server

For production environments, the **Command Transport is not recommended** due to the high overhead of starting a browser engine (Playwright/Chromium) for every request.

### Recommended Pattern
Deploy a long-running **HTTP MCP Server**. This allows:
1. **Persistent Browser Processes**: Keep a single browser instance or pool running to eliminate startup latency.
2. **True State Management**: Maintain real Playwright `BrowserContext` and `Page` objects in memory.
3. **Concurrency**: Handle multiple simultaneous requests from Aries or other clients.

### Configuration
In `config.yaml`, configure the server using a URL instead of a command:

```yaml
providers:
  mcp_servers:
    - id: playwright-prod
      url: "http://localhost:8000"
      timeout_seconds: 60
```

## Security Posture

Aries treats MCP tools as first-class citizens, applying the same policy gates and auditing as built-in tools.

### Risk Levels
The Playwright tools are categorized to allow fine-grained policy control:
- **`exec`**: Used for `browser_new_context` and `page_goto`. These tools change the high-level state of the browser or initiate navigation.
- **`read`**: Used for `page_content`. This extracts data from the current session.
- **`write`**: Used for `page_screenshot`. This writes data (the image) to the local filesystem.

### Network Flags
Aries tracks network requirements to prevent silent data exfiltration:
- `page_goto` is marked with `requires_network: true`.
- Other tools like `page_screenshot` or `page_content` are marked `requires_network: false` as they operate on the already-loaded page.

### Artifact Paths & Isolation
Tools like `page_screenshot` that write to the filesystem must declare `path_params`. 
- **Purpose**: This allows Aries to audit the destination path against the current workspace policies (e.g., ensuring screenshots are only saved in allowed directories).
- **Metadata**: In the Playwright server, `page_screenshot` explicitly defines `"path_params": ["path"]`.

## Interaction with `strict_metadata`

If `providers.strict_metadata: true` is enabled in Aries, the application will fail to start if any MCP tool provides incomplete security metadata.

To satisfy strict mode, Playwright MCP tools must explicitly declare:
1. **`risk`**: Must be one of `read`, `write`, or `exec`.
2. **`requires_network`**: A boolean indicating if the tool itself performs network I/O.
3. **`path_params`**: Required if the tool accepts arguments that are used as local filesystem paths (especially for `write` and `exec` risks).
4. **`emits_artifacts`**: Boolean indicating if the tool produces files/data that should be tracked in the conversation history.

The Aries Playwright server is designed to provide this metadata by default, ensuring it passes strict security audits during initialization.
