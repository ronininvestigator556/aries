from __future__ import annotations

import json

from aries.core.desktop_summary import SummaryBuilder, SummaryOutcome


def _build_builder(summary_format: str) -> SummaryBuilder:
    audit_entries = [
        {
            "event": "policy_check",
            "cached": True,
            "paths_validated": {"path": {"cached": True}},
        },
        {
            "event": "policy_check",
            "cached": False,
            "paths_validated": {"path": {"cached": False}},
        },
        {
            "event": "tool_call",
            "tool": "read_file",
            "audit": {"input": {"path": "notes.txt"}},
            "probe": True,
        },
        {
            "event": "process_output",
            "output": "[no new output]",
        },
    ]
    artifacts = [
        {"path": "artifacts/run.log", "type": "log"},
        {"path": "artifacts/run.diff", "type": "diff"},
        {"path": "notes.txt", "type": "file"},
    ]
    return SummaryBuilder(
        mode="commander",
        audit_entries=audit_entries,
        artifacts=artifacts,
        outcome=SummaryOutcome(status="success"),
        summary_format=summary_format,
    )


def test_summary_json_format_contains_required_keys() -> None:
    builder = _build_builder("json")
    payload = json.loads(builder.build())

    assert payload["outcome"]["status"] == "success"
    assert "work_performed" in payload
    assert "approvals" in payload
    assert "run_stats" in payload
    assert "artifacts" in payload
    assert "citations" in payload

    run_stats = payload["run_stats"]
    assert "steps_executed" in run_stats
    assert "policy_cache_hits" in run_stats
    assert "policy_cache_misses" in run_stats
    assert "path_cache_hits" in run_stats
    assert "path_cache_misses" in run_stats
    assert "output_condensed_count" in run_stats
    assert "probe_steps" in run_stats


def test_summary_markdown_contains_headings() -> None:
    builder = _build_builder("markdown")
    summary = builder.build()
    assert "## Outcome" in summary
    assert "## Work performed" in summary
    assert "## Approvals" in summary
    assert "## Run stats" in summary
    assert "## Artifacts" in summary
