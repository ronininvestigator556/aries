# ARIES Phase 1 Bug Fixes & Completion Tasks

## Context

A previous agent (Codex) implemented Phase 1 features but introduced critical bugs that will break tool execution at runtime. This document outlines required fixes in priority order.

---

## CRITICAL FIXES (Must complete first)

### 1. Fix `ollama_client.chat()` Return Type

**File:** `aries/core/ollama_client.py`

**Problem:** The `chat()` method returns `response["message"]["content"]` (a string), but `cli.py` expects the full response dict to check for `tool_calls`.

**Required Changes:**

```python
async def chat(
    self,
    model: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    **kwargs: Any,
) -> dict[str, Any] | str:
    """Send chat message and get response.
    
    Args:
        model: Model name to use.
        messages: List of message dictionaries.
        tools: Optional list of tool definitions.
        **kwargs: Additional parameters for Ollama.
        
    Returns:
        Full response dict if tools provided, otherwise just content string.
    """
    try:
        response = await self.client.chat(
            model=model,
            messages=messages,
            tools=tools,
            **kwargs,
        )
        # Return full response when tools are provided so caller can check for tool_calls
        if tools:
            return response
        return response["message"]["content"]
    except ollama.ResponseError as e:
        if "not found" in str(e).lower():
            raise OllamaModelError(f"Model not found: {model}") from e
        raise OllamaError(f"Chat failed: {e}") from e
    except Exception as e:
        raise OllamaError(f"Chat failed: {e}") from e
```

**Also update `cli.py`** to handle both return types properly. When tools are NOT provided, `chat()` returns a string, so `_stream_assistant_response()` needs adjustment.

---

### 2. Consolidate Duplicate `ToolResult` Classes

**Problem:** Two different `ToolResult` dataclasses exist with different fields:
- `aries/tools/base.py` — Used by tool execution
- `aries/core/message.py` — Used by conversation/message tracking

**Solution:** Keep BOTH but rename the one in `message.py` to `ToolResultMessage` to clarify its purpose as a message-level construct.

**File:** `aries/core/message.py`

Change:
```python
@dataclass
class ToolResult:
    tool_call_id: str
    ...
```

To:
```python
@dataclass
class ToolResultMessage:
    """Represents a tool result as stored in conversation history."""
    tool_call_id: str
    content: str
    success: bool = True
    error: str | None = None
```

Then update all references in `message.py` and `conversation.py` to use `ToolResultMessage`.

---

### 3. Add Tools Parameter to Streaming Call

**File:** `aries/cli.py`

**Problem:** `_stream_assistant_response()` doesn't pass tools, so if the model decides mid-stream it needs a tool, it can't request one.

**Fix:** In `_stream_assistant_response()`, add tools to the streaming call:

```python
async for chunk in self.ollama.chat_stream(
    model=self.current_model,
    messages=messages,
    tools=self.tool_definitions or None,  # ADD THIS
):
```

**Note:** Ollama streaming with tools may behave differently. Test whether tool_calls come through in stream mode. If not, we may need to detect tool requests and switch to non-streaming for that turn.

---

### 4. Add Loop Guard to Prevent Infinite Tool Loops

**File:** `aries/cli.py`

**Problem:** `_run_assistant()` has a `while True` loop that could hang if tool parsing fails repeatedly or if the model keeps requesting tools.

**Fix:** Add a maximum iteration count:

```python
async def _run_assistant(self) -> None:
    """Run chat loop with optional tool handling."""
    max_tool_iterations = 10
    iteration = 0
    
    while iteration < max_tool_iterations:
        iteration += 1
        messages = self.conversation.get_messages_for_ollama()
        response = await self.ollama.chat(
            model=self.current_model,
            messages=messages,
            tools=self.tool_definitions or None,
        )
        message_payload = response.get("message", {})
        tool_calls_raw = message_payload.get("tool_calls") or []
        
        if tool_calls_raw:
            tool_calls = self.conversation.parse_tool_calls(tool_calls_raw)
            self.conversation.add_assistant_message(
                message_payload.get("content", ""),
                tool_calls=tool_calls,
            )
            await self._execute_tool_calls(tool_calls)
            continue
        
        await self._stream_assistant_response()
        break
    else:
        display_error("Maximum tool iterations reached. Stopping.")
```

---

## MEDIUM PRIORITY FIXES

### 5. Verify `display_info` Exists

**File:** `aries/ui/display.py`

Check if `display_info` function exists. If not, add it:

```python
def display_info(message: str) -> None:
    """Display an informational message."""
    console.print(f"[blue]ℹ[/blue] {message}")
```

---

### 6. Add Image Path Detection for Vision Models

**File:** `aries/cli.py`

**Problem:** Users can't easily use vision models like Llava. They'd have to manually invoke the read_image tool.

**Enhancement:** Detect file paths in user messages that look like images and automatically load them.

Add a helper method to `Aries` class:

```python
import re

async def _extract_images_from_message(self, message: str) -> tuple[str, list[str]]:
    """Extract image paths from message and load them.
    
    Args:
        message: User message potentially containing image paths.
        
    Returns:
        Tuple of (cleaned message, list of base64 images).
    """
    # Pattern to match Windows and Unix file paths ending in image extensions
    pattern = r'([A-Za-z]:\\[^\s]+\.(?:jpg|jpeg|png|gif|webp)|/[^\s]+\.(?:jpg|jpeg|png|gif|webp))'
    matches = re.findall(pattern, message, re.IGNORECASE)
    
    if not matches:
        return message, []
    
    images = []
    from aries.tools.image import ReadImageTool
    image_tool = ReadImageTool()
    
    for path in matches:
        result = await image_tool.execute(path=path)
        if result.success:
            images.append(result.content)
    
    return message, images
```

Then update `handle_chat()`:

```python
async def handle_chat(self, message: str) -> None:
    """Handle a chat message - send to LLM and display response."""
    cleaned_message, images = await self._extract_images_from_message(message)
    self.conversation.add_user_message(cleaned_message, images=images if images else None)
    await self._run_assistant()
```

---

### 7. Limit Tool Output Display Size

**File:** `aries/cli.py`

**Problem:** Large tool outputs (like reading a huge file) could flood the console.

**Fix:** In `_execute_tool_calls()`, truncate displayed output:

```python
MAX_DISPLAY_CHARS = 2000

if output:
    display_output = output[:MAX_DISPLAY_CHARS]
    if len(output) > MAX_DISPLAY_CHARS:
        display_output += f"\n... (truncated, {len(output)} total chars)"
    console.print(f"\n[dim]{call.name} output:[/dim]\n{display_output}\n")
```

---

## VERIFICATION STEPS

After making fixes, verify:

1. **Tool Execution Flow:**
   - Start Aries
   - Ask: "List the files in the current directory"
   - Confirm `list_directory` tool is called and output is shown
   - Confirm assistant responds based on tool output

2. **Image Loading (if vision model available):**
   - Switch to a vision model: `/model llava`
   - Ask: "Describe the image at C:\path\to\image.jpg"
   - Confirm image is loaded and analyzed

3. **Shell Execution:**
   - Ask: "Run `echo hello` in the shell"
   - Confirm `execute_shell` tool works

4. **Loop Guard:**
   - Create a scenario where tools might loop
   - Confirm it stops at max iterations

5. **No Crashes:**
   - Run through several tool calls without errors
   - Test with missing files, bad paths, timeouts

---

## FILES TO MODIFY

1. `aries/core/ollama_client.py` — Fix chat() return type
2. `aries/core/message.py` — Rename ToolResult to ToolResultMessage
3. `aries/core/conversation.py` — Update ToolResult references
4. `aries/cli.py` — Loop guard, tools in streaming, image detection, output truncation
5. `aries/ui/display.py` — Verify/add display_info

---

## DO NOT MODIFY

- `aries/tools/base.py` — ToolResult here is correct for tool execution
- `aries/tools/filesystem.py` — Working correctly
- `aries/tools/shell.py` — Working correctly  
- `aries/tools/image.py` — Working correctly
- `aries/commands/*` — Not related to these bugs
