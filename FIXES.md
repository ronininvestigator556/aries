# ARIES Critical Bug Fixes

Three bugs will crash the application at runtime. Fix these in order.

---

## Bug 1: Undefined `tools` in `ollama_client.py`

**File:** `aries/core/ollama_client.py`
**Line:** ~95

**Problem:** The `chat()` method references `tools` but it's not in the function signature.

**Current code (broken):**
```python
async def chat(
    self,
    model: str,
    messages: list[dict[str, Any]],
    *,
    raw: bool = False,
    **kwargs: Any,
) -> Any:
    # ...
    response = await self.client.chat(
        model=model,
        messages=messages,
        tools=tools,  # 'tools' is undefined!
        **kwargs,
    )
```

**Fix:** Add `tools` parameter to function signature:

```python
async def chat(
    self,
    model: str,
    messages: list[dict[str, Any]],
    *,
    tools: list[dict[str, Any]] | None = None,
    raw: bool = False,
    **kwargs: Any,
) -> Any:
    # ...
    response = await self.client.chat(
        model=model,
        messages=messages,
        tools=tools,
        **kwargs,
    )
```

---

## Bug 2: Duplicate/Invalid Class in `message.py`

**File:** `aries/core/message.py`
**Lines:** 31-43

**Problem:** Two `ToolResultMessage` classes defined. Second one inherits from `ToolResult` which doesn't exist in this file.

**Current code (broken):**
```python
@dataclass
class ToolResultMessage:
    """Represents a tool result as stored in conversation history."""
    tool_call_id: str
    content: str
    success: bool = True
    error: str | None = None


@dataclass
class ToolResultMessage(ToolResult):  # ToolResult doesn't exist! Duplicate class name!
    """Represents a tool result embedded in the conversation history."""
    name: str | None = None
```

**Fix:** Remove the duplicate, merge into single class:

```python
@dataclass
class ToolResultMessage:
    """Represents a tool result as stored in conversation history."""
    tool_call_id: str
    content: str
    success: bool = True
    error: str | None = None
    name: str | None = None
```

---

## Bug 3: Undefined `message` in `cli.py`

**File:** `aries/cli.py`
**Line:** ~158

**Problem:** `_run_assistant()` references `message` variable that doesn't exist.

**Current code (broken):**
```python
async def _run_assistant(self) -> None:
    """Run chat loop with optional tool handling."""
    max_tool_iterations = 10
    iteration = 0

    while iteration < max_tool_iterations:
        iteration += 1
        messages = self.conversation.get_messages_for_ollama()
        if self.current_rag:
            context_chunks = await self._retrieve_context(message)  # 'message' undefined!
```

**Fix:** Get the last user message from conversation:

```python
async def _run_assistant(self) -> None:
    """Run chat loop with optional tool handling."""
    max_tool_iterations = 10
    iteration = 0

    # Get the user's query for RAG retrieval
    last_user_msg = self.conversation.get_last_user_message()
    user_query = last_user_msg.content if last_user_msg else ""

    while iteration < max_tool_iterations:
        iteration += 1
        messages = self.conversation.get_messages_for_ollama()
        if self.current_rag and user_query:
            context_chunks = await self._retrieve_context(user_query)
```

---

## Verification

After fixes, run:

```bash
cd C:\Users\muram\Dev\aries
python -c "from aries.core.message import ToolResultMessage; print('message.py OK')"
python -c "from aries.core.ollama_client import OllamaClient; print('ollama_client.py OK')"
python -c "from aries.cli import Aries; print('cli.py OK')"
python -m aries
```

All imports should succeed. Then test:
1. Basic chat works
2. `/model list` works
3. Tool execution works (ask model to list files in current directory)

---

## Files to Modify

1. `aries/core/ollama_client.py` — Add `tools` parameter
2. `aries/core/message.py` — Remove duplicate class, merge fields
3. `aries/cli.py` — Fix undefined `message` variable
