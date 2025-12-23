"""
CLI-based MCP server for Playwright integration.
Supports 'stub' mode for testing without a real browser.
"""
import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# Constants
ENV_STUB_MODE = "ARIES_PLAYWRIGHT_STUB"
STUB_STATE_FILE = "aries_playwright_stub_state.json"

TOOLS = [
    {
        "name": "browser_new_context",
        "description": "Create a new browser context/session.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        },
        "risk": "exec",
        "requires_network": False,
        "emits_artifacts": False,
        "metadata": {
            "result_schema": {"context_id": "string"}
        }
    },
    {
        "name": "page_goto",
        "description": "Navigate a page to a URL.",
        "parameters": {
            "type": "object",
            "properties": {
                "context_id": {"type": "string"},
                "url": {"type": "string"}
            },
            "required": ["context_id", "url"]
        },
        "risk": "exec",
        "requires_network": True,
        "emits_artifacts": False
    },
    {
        "name": "page_screenshot",
        "description": "Take a screenshot of the current page.",
        "parameters": {
            "type": "object",
            "properties": {
                "context_id": {"type": "string"},
                "path": {"type": "string", "description": "Output path for the screenshot"},
                "full_page": {"type": "boolean", "default": False}
            },
            "required": ["context_id", "path"]
        },
        "risk": "write",
        "requires_network": False,
        "emits_artifacts": True,
        "path_params": ["path"]
    },
    {
        "name": "page_content",
        "description": "Get the HTML content of the page.",
        "parameters": {
            "type": "object",
            "properties": {
                "context_id": {"type": "string"}
            },
            "required": ["context_id"]
        },
        "risk": "read",
        "requires_network": False,
        "emits_artifacts": False
    },
    {
        "name": "browser_close_context",
        "description": "Close a browser context.",
        "parameters": {
            "type": "object",
            "properties": {
                "context_id": {"type": "string"}
            },
            "required": ["context_id"]
        },
        "risk": "exec",
        "requires_network": False,
        "emits_artifacts": False
    }
]

def _get_stub_state_path() -> Path:
    override = os.environ.get("ARIES_PLAYWRIGHT_STUB_STATE_PATH")
    if override:
        return Path(override)
    return Path(tempfile.gettempdir()) / STUB_STATE_FILE

def _load_stub_state() -> Dict[str, Any]:
    path = _get_stub_state_path()
    if not path.exists():
        return {"contexts": {}}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"contexts": {}}

def _save_stub_state(state: Dict[str, Any]) -> None:
    path = _get_stub_state_path()
    path.write_text(json.dumps(state), encoding="utf-8")

def handle_list_tools():
    print(json.dumps({"tools": TOOLS, "version": "0.1.0"}))

def handle_invoke(tool_name: str, args_json: str):
    try:
        args = json.loads(args_json)
        if not isinstance(args, dict):
            print(json.dumps({"success": False, "error": "Arguments must be a JSON object"}))
            return
    except json.JSONDecodeError:
        print(json.dumps({"success": False, "error": "Invalid JSON arguments"}))
        return

    # Check for Stub Mode
    if os.environ.get(ENV_STUB_MODE):
        _handle_stub_invoke(tool_name, args)
    else:
        # TODO: Implement real Playwright daemon connection here
        print(json.dumps({
            "success": False, 
            "error": "Real Playwright mode not implemented in this increment. Use ARIES_PLAYWRIGHT_STUB=1."
        }))

def _handle_stub_invoke(tool_name: str, args: Dict[str, Any]):
    state = _load_stub_state()
    result = {"success": True, "content": "", "metadata": {}, "artifacts": []}
    
    try:
        if tool_name == "browser_new_context":
            cid = f"ctx_{int(time.time())}"
            state["contexts"][cid] = {"url": "about:blank"}
            result["content"] = f"Context created: {cid}"
            result["metadata"] = {"context_id": cid}
            
        elif tool_name == "page_goto":
            cid = args.get("context_id")
            url = args.get("url")
            if cid not in state["contexts"]:
                raise ValueError(f"Context {cid} not found")
            state["contexts"][cid]["url"] = url
            result["content"] = f"Navigated to {url}"
            
        elif tool_name == "page_screenshot":
            cid = args.get("context_id")
            path_str = args.get("path")
            if not path_str:
                raise ValueError("Path required")
            if cid not in state["contexts"]:
                raise ValueError(f"Context {cid} not found")
                
            # Create a dummy file
            path = Path(path_str)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"FAKE_SCREENSHOT_DATA")
            
            result["content"] = f"Screenshot saved to {path}"
            result["artifacts"].append({
                "path": str(path),
                "type": "image",
                "mime": "image/png",
                "description": f"Screenshot of {state['contexts'][cid]['url']}"
            })
            
        elif tool_name == "page_content":
            cid = args.get("context_id")
            if cid not in state["contexts"]:
                raise ValueError(f"Context {cid} not found")
            result["content"] = f"<html><body>Content of {state['contexts'][cid]['url']}</body></html>"
            
        elif tool_name == "browser_close_context":
            cid = args.get("context_id")
            if cid in state["contexts"]:
                del state["contexts"][cid]
            result["content"] = f"Context {cid} closed"
            
        else:
            result["success"] = False
            result["error"] = f"Unknown tool: {tool_name}"
            
        _save_stub_state(state)
        print(json.dumps(result))
        
    except Exception as e:
        print(json.dumps({"success": False, "error": str(e)}))

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--list-tools", action="store_true")
    parser.add_argument("--invoke", help="Tool name to invoke")
    parser.add_argument("--args", help="JSON arguments for invocation")
    
    args = parser.parse_args()
    
    if args.list_tools:
        handle_list_tools()
    elif args.invoke:
        handle_invoke(args.invoke, args.args)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
