import json

import pytest

from aries.core.conversation import Conversation
from aries.core.message import Message, Role


def test_message_pruning_by_count() -> None:
    convo = Conversation(max_messages=3, max_context_tokens=10_000)
    for idx in range(5):
        convo.add_user_message(f"msg {idx}")
    assert len(convo) == 3
    assert convo.get_last_user_message().content == "msg 4"


def test_message_pruning_by_tokens() -> None:
    convo = Conversation(max_messages=10, max_context_tokens=25)
    convo.add_user_message("short message")
    convo.add_user_message("b" * 15)
    assert len(convo) == 1
    assert convo.get_last_user_message().content == "b" * 15


def test_tool_call_parsing_and_formatting() -> None:
    raw_calls = [
        {
            "id": "call-1",
            "function": {"name": "read_file", "arguments": json.dumps({"path": "foo.txt"})},
        }
    ]
    convo = Conversation()
    parsed = convo.parse_tool_calls(raw_calls)
    assert parsed[0].name == "read_file"
    assert parsed[0].arguments == {"path": "foo.txt"}

    msg = Message.assistant("Using tool", tool_calls=parsed)
    formatted = msg.to_ollama_format()
    assert formatted["tool_calls"][0]["function"]["name"] == "read_file"
    assert formatted["tool_calls"][0]["id"] == "call-1"


def test_tool_result_message_records_role() -> None:
    convo = Conversation()
    result_msg = convo.add_tool_result_message(
        tool_call_id="abc",
        content="done",
        success=True,
    )
    assert result_msg.role == Role.TOOL
    assert result_msg.tool_results and result_msg.tool_results[0].tool_call_id == "abc"
