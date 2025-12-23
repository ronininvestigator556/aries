from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aries.commands.model import ModelCommand


@pytest.mark.asyncio
async def test_model_use_subcommand_switches_model():
    app = MagicMock()
    app.current_model = "old-model"
    app.ollama.model_exists = AsyncMock(return_value=True)

    cmd = ModelCommand()

    with patch("aries.commands.model.display_success") as mock_success:
        await cmd.execute(app, "use llama3.1:latest")

    app.ollama.model_exists.assert_awaited_once_with("llama3.1:latest")
    assert app.current_model == "llama3.1:latest"
    mock_success.assert_called_once_with("Switched to model: llama3.1:latest")


@pytest.mark.asyncio
async def test_model_set_subcommand_switches_model():
    app = MagicMock()
    app.current_model = "old-model"
    app.ollama.model_exists = AsyncMock(return_value=True)

    cmd = ModelCommand()

    with patch("aries.commands.model.display_success") as mock_success:
        await cmd.execute(app, "set cerberus-v2:latest")

    app.ollama.model_exists.assert_awaited_once_with("cerberus-v2:latest")
    assert app.current_model == "cerberus-v2:latest"
    mock_success.assert_called_once_with("Switched to model: cerberus-v2:latest")


def test_model_help_includes_subcommands_and_examples():
    cmd = ModelCommand()
    help_text = cmd.get_help()

    assert "/model list" in help_text
    assert "/model <model_name>" in help_text
    assert "/model use <model_name>" in help_text
    assert "/model set <model_name>" in help_text
    assert "/model switch <model_name>" in help_text
    assert "/model llama3.2:latest" in help_text
    assert "/model use llama3.1:latest" in help_text
