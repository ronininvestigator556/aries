from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aries.cli import (
    TOOL_CALL_INVALID_ARGUMENTS,
    TOOL_CALL_PARSE_ERROR,
    Aries,
)
from aries.config import Config


@pytest.fixture
def aries_app():
    config = Config()
    app = Aries(config)
    app.ollama = AsyncMock()
    app.ollama.is_available.return_value = True

    # Mock tool registry
    tool = MagicMock()
    tool.name = "required_tool"
    tool.qualified_id = "required_tool"
    # Provide parameters schema
    tool.parameters = {
        "type": "object",
        "properties": {"arg1": {"type": "string"}},
        "required": ["arg1"]
    }
    tool.risk_level = "read"
    tool.mutates_state = False

    # We need to mock resolve_with_id to return our mock tool
    app.tool_registry.resolve_with_id = MagicMock(return_value=(tool, tool))

    return app

@pytest.mark.asyncio
async def test_malformed_json_tool_call(aries_app):
    # Setup
    aries_app.ollama.chat.return_value = {
        "message": {
            "content": "Thinking...",
            "tool_calls": [
                {
                    "function": {
                        "name": "required_tool",
                        "arguments": "{invalid_json"
                    }
                }
            ]
        }
    }

    # Run
    aries_app.conversation.add_user_message("test")
    await aries_app._run_assistant()

    # Verify
    # Check if tool result was added with error
    assert len(aries_app.conversation.messages) > 1
    last_msg = aries_app.conversation.messages[-1]
    assert last_msg.role == "tool"
    # We look at the first result in the tool message
    assert last_msg.tool_results[0].error == TOOL_CALL_PARSE_ERROR

    # Verify tool was NOT executed
    tool_mock = aries_app.tool_registry.resolve_with_id.return_value[1]
    tool_mock.execute.assert_not_called()

@pytest.mark.asyncio
async def test_empty_args_required_tool(aries_app):
    aries_app.ollama.chat.return_value = {
        "message": {
            "content": "",
            "tool_calls": [
                {
                    "function": {
                        "name": "required_tool",
                        "arguments": {}
                    }
                }
            ]
        }
    }

    aries_app.conversation.add_user_message("test")
    await aries_app._run_assistant()

    last_msg = aries_app.conversation.messages[-1]
    assert last_msg.role == "tool"
    assert last_msg.tool_results[0].error == TOOL_CALL_INVALID_ARGUMENTS

    tool_mock = aries_app.tool_registry.resolve_with_id.return_value[1]
    tool_mock.execute.assert_not_called()

@pytest.mark.asyncio
async def test_non_actionable_response(aries_app):
    aries_app.config.ui.stream_output = False  # Disable streaming for easier mocking
    aries_app.ollama.chat.return_value = {
        "message": {
            "content": "Okay.",
            "tool_calls": []
        }
    }

    with patch("aries.cli.display_warning") as mock_warn:
        aries_app.conversation.add_user_message("test")
        await aries_app._run_assistant()

        # Verify warning called with expected text
        found = False
        for call in mock_warn.call_args_list:
            if "Model response contained no actionable content" in call[0][0]:
                found = True
                break
        assert found

@pytest.mark.asyncio
async def test_missing_tool_name(aries_app):
    aries_app.ollama.chat.return_value = {
        "message": {
            "content": "",
            "tool_calls": [
                {
                    "function": {
                        "name": "",  # Empty name
                        "arguments": {}
                    }
                }
            ]
        }
    }

    aries_app.conversation.add_user_message("test")
    await aries_app._run_assistant()

    last_msg = aries_app.conversation.messages[-1]
    assert last_msg.role == "tool"
    assert last_msg.tool_results[0].error == TOOL_CALL_PARSE_ERROR

@pytest.mark.asyncio
async def test_stream_whitespace_only_warns_without_blank_lines(aries_app, capsys):
    aries_app.conversation.add_user_message("test")
    aries_app.ollama.chat.return_value = {"message": {"content": ""}}

    async def whitespace_stream(*_, **__):
        for chunk in ["\n", "   ", "\n\n"]:
            yield chunk

    aries_app.ollama.chat_stream = whitespace_stream

    await aries_app._run_assistant()

    captured = capsys.readouterr().out
    assert "Model returned an empty response" in captured
    assert "\n\n\n" not in captured
    assert aries_app.last_model_turn is not None
    assert aries_app.last_model_turn.get("stripped_response_length") == 0

@pytest.mark.asyncio
async def test_stream_suppresses_leading_whitespace_then_streams(aries_app, capsys):
    aries_app.conversation.add_user_message("test")
    aries_app.ollama.chat.return_value = {"message": {"content": ""}}

    async def mixed_stream(*_, **__):
        for chunk in ["\n\n", "  ", "Hello", " world"]:
            yield chunk

    aries_app.ollama.chat_stream = mixed_stream

    await aries_app._run_assistant()

    captured = capsys.readouterr().out
    assert captured.startswith("\nHello")
    assert "Hello world" in captured
    assert not captured.startswith("\n\n")


@pytest.mark.asyncio
async def test_empty_response_adds_rag_hint_for_knowledge_prompt(aries_app):
    aries_app.config.ui.stream_output = False
    aries_app.ollama.chat.return_value = {"message": {"content": "", "tool_calls": []}}
    aries_app._ensure_rag_components = MagicMock(return_value=True)
    aries_app.indexer = MagicMock()
    aries_app.indexer.list_indices.return_value = ["docs"]

    with patch("aries.cli.display_warning") as mock_warn:
        aries_app.conversation.add_user_message("Summarize the book about ARIES.")
        await aries_app._run_assistant()

    assert any(
        "Tip: Select an index with `/rag use <id>`" in call.args[0]
        for call in mock_warn.call_args_list
    )


@pytest.mark.asyncio
async def test_empty_response_skips_rag_hint_for_non_knowledge_prompt(aries_app):
    aries_app.config.ui.stream_output = False
    aries_app.ollama.chat.return_value = {"message": {"content": "", "tool_calls": []}}
    aries_app._ensure_rag_components = MagicMock(return_value=True)
    aries_app.indexer = MagicMock()
    aries_app.indexer.list_indices.return_value = ["docs"]

    with patch("aries.cli.display_warning") as mock_warn:
        aries_app.conversation.add_user_message("Hello there.")
        await aries_app._run_assistant()

    assert any(
        "Model returned an empty response" in call.args[0]
        for call in mock_warn.call_args_list
    )
    assert all(
        "Tip: Select an index with `/rag use <id>`" not in call.args[0]
        for call in mock_warn.call_args_list
    )
