import json
import os
import sys
import tempfile
from pathlib import Path

import pytest
from aries.config import Config, MCPServerConfig, WorkspaceConfig
from aries.core.workspace import ArtifactRegistry, WorkspaceManager
from aries.providers.mcp import MCPProvider

# Path to the bundled server
SERVER_SCRIPT = Path("aries/providers/playwright_server/server.py").absolute()

@pytest.fixture
def stub_env(tmp_path):
    """Set up environment for stub mode."""
    state_file = tmp_path / "stub_state.json"
    os.environ["ARIES_PLAYWRIGHT_STUB"] = "1"
    os.environ["ARIES_PLAYWRIGHT_STUB_STATE_PATH"] = str(state_file)
    yield
    if "ARIES_PLAYWRIGHT_STUB" in os.environ:
        del os.environ["ARIES_PLAYWRIGHT_STUB"]
    if "ARIES_PLAYWRIGHT_STUB_STATE_PATH" in os.environ:
        del os.environ["ARIES_PLAYWRIGHT_STUB_STATE_PATH"]

@pytest.fixture
def workspace_manager(tmp_path):
    """Create a temporary workspace manager."""
    config = WorkspaceConfig(root=tmp_path)
    wm = WorkspaceManager(config)
    wm.new("test_ws")
    return wm

@pytest.fixture
def mcp_provider(stub_env):
    """Create an MCP provider instance connected to the stub server."""
    config = MCPServerConfig(
        id="playwright",
        command=[sys.executable, str(SERVER_SCRIPT)],
        # config.env is merged on top of os.environ, so we don't strictly need to duplicate here
        # if stub_env sets it, but keeping it explicit for the test logic if needed.
        # However, to test inheritance, let's rely on os.environ for stub mode 
        # but passing it here ensures it's in the client's view if logic changes.
        env={"ARIES_PLAYWRIGHT_STUB": "1"}
    )
    provider = MCPProvider(config, strict=True)
    return provider

@pytest.mark.asyncio
async def test_server_connection_and_listing(mcp_provider):
    """Verify we can connect and list tools."""
    assert mcp_provider.connected
    tools = mcp_provider.list_tools()
    assert len(tools) >= 5
    tool_names = {t.name for t in tools}
    assert "page_screenshot" in tool_names
    assert "page_goto" in tool_names

@pytest.mark.asyncio
async def test_tool_metadata(mcp_provider):
    """Verify tool metadata is correctly mapped."""
    tools = {t.name: t for t in mcp_provider.list_tools()}
    
    screenshot = tools["page_screenshot"]
    assert screenshot.risk_level == "write"
    assert screenshot.emits_artifacts is True
    assert "path" in screenshot.path_params
    
    goto = tools["page_goto"]
    assert goto.risk_level == "exec"
    assert goto.tool_requires_network is True

@pytest.mark.asyncio
async def test_full_workflow(mcp_provider, workspace_manager):
    """Simulate a workflow: New Context -> Goto -> Screenshot."""
    tools = {t.name: t for t in mcp_provider.list_tools()}
    workspace = workspace_manager.current
    
    # 1. New Context
    res1 = await tools["browser_new_context"].execute()
    assert res1.success
    cid = res1.metadata.get("context_id")
    assert cid
    
    # 2. Goto
    res2 = await tools["page_goto"].execute(context_id=cid, url="http://example.com")
    assert res2.success
    assert "Navigated to" in res2.content
    
    # 3. Screenshot
    # Path must be absolute for the stub to write to it
    screenshot_path = workspace.root / "shot.png"
    
    res3 = await tools["page_screenshot"].execute(
        context_id=cid, 
        path=str(screenshot_path),
        workspace=workspace
    )
    assert res3.success
    assert res3.artifacts
    assert len(res3.artifacts) == 1
    artifact = res3.artifacts[0]
    assert artifact["path"] == str(screenshot_path)
    assert artifact["type"] == "image"
    
    # Verify file was created
    assert screenshot_path.exists()
    assert screenshot_path.read_bytes() == b"FAKE_SCREENSHOT_DATA"
    
    # Verify it can be registered
    record = workspace_manager.register_artifact_hint(artifact)
    assert record
    assert record["path"] == str(screenshot_path)
    assert record["mime_type"] == "image/png"

@pytest.mark.asyncio
async def test_path_safety_enforcement(mcp_provider, workspace_manager, tmp_path):
    """Verify that paths outside the workspace are rejected by the client."""
    tools = {t.name: t for t in mcp_provider.list_tools()}
    workspace = workspace_manager.current
    
    # Create context
    res1 = await tools["browser_new_context"].execute()
    cid = res1.metadata.get("context_id")
    
    # Try to write screenshot outside workspace (using a separate temp dir)
    # tmp_path is the root for workspace_manager but we can use a sibling or parent
    unsafe_dir = tmp_path / "unsafe"
    unsafe_dir.mkdir()
    unsafe_path = unsafe_dir / "out.png"
    
    res = await tools["page_screenshot"].execute(
        context_id=cid, 
        path=str(unsafe_path),
        workspace=workspace
    )
    
    assert not res.success
    error_msg = res.error or ""
    assert (
        "escapes workspace" in error_msg 
        or "denied by policy" in error_msg
        or "Path outside allowed locations" in error_msg
    )


