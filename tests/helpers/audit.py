from __future__ import annotations

from typing import Iterable


def assert_policy_entry_complete(entry: dict[str, object]) -> None:
    required_keys = {
        "tool_id",
        "risk_level",
        "approval_required",
        "approval_result",
        "paths_validated",
        "start_time",
        "end_time",
    }
    missing = required_keys - set(entry)
    assert not missing, f"Missing keys: {sorted(missing)}"
    assert entry["start_time"], "start_time must be set"
    assert entry["end_time"], "end_time must be set"


def assert_policy_entries_cover_tool_calls(
    policy_entries: Iterable[dict[str, object]],
    tool_calls: Iterable[dict[str, object]],
) -> None:
    policy_by_tool = {}
    for entry in policy_entries:
        tool_id = str(entry.get("tool_id", ""))
        tool_name = tool_id.split(":")[-1]
        policy_by_tool.setdefault(tool_name, []).append(entry)

    for call in tool_calls:
        tool_name = str(call.get("tool", "")).split(":")[-1]
        matches = policy_by_tool.get(tool_name)
        assert matches, f"Missing policy entry for tool {tool_name}"
        for entry in matches:
            assert_policy_entry_complete(entry)
