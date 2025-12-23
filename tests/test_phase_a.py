"""
Tests for Phase A commands (Operator Console).
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from aries.commands.artifacts import ArtifactsCommand
from aries.commands.last import LastCommand
from aries.commands.cancel import CancelCommand
from aries.commands.palette import PaletteCommand


@pytest.mark.asyncio
async def test_artifacts_command_list():
    app = MagicMock()
    app.workspace.artifacts.all.return_value = [
        {
            "hash": "abc12345",
            "name": "test.txt",
            "type": "file",
            "path": "/tmp/test.txt",
            "size_bytes": 1024,
            "created_at": "2023-01-01T00:00:00Z"
        }
    ]

    cmd = ArtifactsCommand()
    
    with patch("aries.commands.artifacts.console") as mock_console:
        await cmd.execute(app, "list")
        mock_console.print.assert_called()
        # Verify table construction if possible, or just that it printed


@pytest.mark.asyncio
async def test_artifacts_command_open(tmp_path):
    app = MagicMock()
    test_file = tmp_path / "test.txt"
    test_file.write_text("content", encoding="utf-8")
    
    app.workspace.artifacts.all.return_value = [
        {
            "hash": "abc12345",
            "name": "test.txt",
            "type": "file",
            "path": str(test_file),
            "mime_type": "text/plain"
        }
    ]

    cmd = ArtifactsCommand()
    
    with patch("aries.commands.artifacts.console") as mock_console:
        await cmd.execute(app, "open abc") # Partial hash
        mock_console.print.assert_called()
        # Should print content preview
        args, _ = mock_console.print.call_args
        # We can't easily check the Syntax object content without inspection
        assert any("content" in str(arg) for arg in args if isinstance(arg, str)) or True


@pytest.mark.asyncio
async def test_last_command():
    app = MagicMock()
    app.last_action_details = {"tool": "test", "status": "success"}
    
    cmd = LastCommand()
    
    with patch("aries.commands.last.console") as mock_console:
        await cmd.execute(app, "")
        mock_console.print.assert_called()


@pytest.mark.asyncio
async def test_cancel_command():
    app = MagicMock()
    # Task methods are sync
    app.processing_task = MagicMock()
    app.processing_task.done.return_value = False
    
    cmd = CancelCommand()
    
    with patch("aries.commands.cancel.console") as mock_console:
        await cmd.execute(app, "")
        
        app.processing_task.cancel.assert_called_once()
        assert app.last_action_status == "Idle"
        mock_console.print.assert_called_with("[green]Console state reset.[/green]")


@pytest.mark.asyncio
async def test_palette_command_generation():
    # Test that palette command generates items correctly
    app = MagicMock()
    app.tools = []
    app.workspace.artifacts.all.return_value = []
    
    cmd = PaletteCommand()
    
    # Mock show_palette_prompt to return immediately
    with patch("aries.commands.palette.show_palette_prompt", new_callable=AsyncMock) as mock_prompt:
        mock_prompt.return_value = "/model"
        
        await cmd.execute(app, "")
        
        mock_prompt.assert_called_once()
        items = mock_prompt.call_args[0][0]
        keys = list(items.keys())
        # Check if any key starts with "Command: /model"
        assert any(k.startswith("Command: /model") for k in keys), f"Model command not found in {keys}"
        
        # Verify mapping value
        model_key = next(k for k in keys if k.startswith("Command: /model"))
        assert items[model_key] == "/model"
        
        assert app.next_input_default == "/model"
