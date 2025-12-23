# Aries User Guide: Get Things Done

Aries is a command-line AI assistant that runs entirely on your local machine. It connects to local LLMs (like Ollama) to help you code, research, and analyze documents without sending your data to the cloud.

This guide skips the theory and focuses on how to use it right now.

---

## 1. Quick Setup

### Prerequisites
1.  **Install Python 3.11+**
2.  **Install Ollama**: [https://ollama.com](https://ollama.com)
    *   Pull a model: `ollama pull llama3` (or `mistral`, `phi3`, etc.)

### Installation
Run this from the `aries` directory:

```bash
pip install -e .
```

### Configuration
1.  Copy the example config:
    ```bash
    cp config.example.yaml config.yaml
    ```
2.  Open `config.yaml` and ensure `ollama_base_url` is correct (usually `http://localhost:11434`).

### Start Aries
```bash
python -m aries
```

---

## 2. Basic Chatting

Once Aries is running, just type your message and hit Enter.

*   **Chat:** `How do I reverse a list in Python?`
*   **Multiline:** Press `Alt+Enter` (or `Esc` then `Enter`) to add a new line without sending.
*   **Clear History:** Type `/clear` to wipe the current conversation context.
*   **Quit:** Type `/exit` or `/quit`.

### Switch Models
Want to use a different LLM?
```bash
/model list           # See what models you have
/model set llama3     # Switch to llama3
```

---

## 3. Chat with Your Documents (RAG)

Aries can read your local files (PDF, Markdown, Text) and answer questions about them.

**1. Index a folder or file:**
Tell Aries to read a directory. It will scan, chunk, and embed the files into a local database.
```bash
/rag index ./my_project_docs
```

**2. Ask questions:**
Once indexed, the AI automatically knows about the content.
*   `Summarize the project roadmap I just indexed.`
*   `What does the CONTRIBUTING.md say about pull requests?`

**3. Search directly:**
If you just want to find relevant snippets without an AI answer:
```bash
/rag search "deployment error codes"
```

---

## 4. Web Search

Aries can search the web for real-time info (requires a configured search provider in `config.yaml`, usually SearXNG).

```bash
/search "latest python 3.12 features"
```
The AI will fetch the results and summarize the answer for you.

---

## 5. Workspaces (Projects)

Keep your work separate. Workspaces store your chat history, indexed documents (RAG), and configuration for a specific project.

```bash
/workspace list            # Show all workspaces
/workspace new project_x   # Create a new one
/workspace open project_x  # Switch to it
```
*Tip: When you switch workspaces, your chat history and RAG index switch too.*

---

## 6. Advanced: Agent Runs

For complex tasks that require multiple steps (planning -> execution), use the `/run` command.

```bash
/run "Refactor the authentication module to use JWTs"
```
Aries will:
1.  Propose a plan.
2.  Ask for your approval.
3.  Execute tools (edit files, run commands) step-by-step.

---

## 7. Useful Commands Cheat Sheet

| Command | Description |
| :--- | :--- |
| `/help` | Show all available commands |
| `/clear` | Clear current chat history |
| `/last` | Show the last message again (useful for copy-pasting) |
| `/profile list` | See available AI personas (e.g., Coder, Writer) |
| `/profile use <name>` | Switch persona |
| `/rag status` | See how many documents are currently indexed |
