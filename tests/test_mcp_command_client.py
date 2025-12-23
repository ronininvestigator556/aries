import json
import os
import sys
from typing import Any
from unittest.mock import MagicMock

import pytest
from aries.config import MCPServerConfig
from aries.providers.mcp import CommandMCPClient

def test_command_client_env_merging():
    """Verify os.environ is merged with config.env."""
    key = "ARIES_TEST_ENV_VAR"
    val = "unique_val"
    os.environ[key] = val
    try:
        config = MCPServerConfig(
            id="test",
            command=["echo"],
            env={"ANOTHER_VAR": "foo"}
        )
        client = CommandMCPClient(config)
        assert client.env[key] == val
        assert client.env["ANOTHER_VAR"] == "foo"
        # Ensure config.env takes precedence if needed, but current implementation merges config.env (update) over os.environ.
        # So config.env wins.
        # Let's verify that.
        os.environ["COLLISION"] = "os"
        config = MCPServerConfig(
            id="test2",
            command=["echo"],
            env={"COLLISION": "config"}
        )
        client2 = CommandMCPClient(config)
        assert client2.env["COLLISION"] == "config"
    finally:
        del os.environ[key]
        if "COLLISION" in os.environ:
            del os.environ["COLLISION"]

def test_command_client_invoke_args_format():
    """Verify invoke sends args directly in --args."""
    from unittest.mock import patch
    
    with patch("subprocess.run") as mock_run:
        # minimal valid JSON response for invoke
        mock_run.return_value.stdout = '{"success": true}'
        
        config = MCPServerConfig(id="test", command=["mycmd"])
        client = CommandMCPClient(config)
        
        client.invoke("mytool", {"arg1": "val1"})
        
        # Check arguments
        call_args = mock_run.call_args[0][0]
        assert "--invoke" in call_args
        assert "mytool" in call_args
        assert "--args" in call_args
        idx = call_args.index("--args")
        payload = call_args[idx+1]
        
        data = json.loads(payload)
        assert data == {"arg1": "val1"}
        # Should NOT be {"tool": ..., "arguments": ...}
        assert "tool" not in data
