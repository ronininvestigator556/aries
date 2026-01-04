from __future__ import annotations

from pathlib import Path

from aries.cli import Aries
from aries.config import Config
from datetime import datetime

from aries.core.desktop_ops import DesktopOpsController, OutputCondenser, ProcessHandle


def test_streaming_output_repetition_condensed() -> None:
    condenser = OutputCondenser(max_bytes=200, max_lines=5)
    first = condenser.condense("hello")
    second = condenser.condense("hello")
    assert first == "hello"
    assert second == "[no new output]"


def test_streaming_output_errors_never_condensed() -> None:
    condenser = OutputCondenser(max_bytes=200, max_lines=5)
    first = condenser.condense("ERROR: failed to connect")
    second = condenser.condense("ERROR: failed to connect")
    assert first == "ERROR: failed to connect"
    assert second == "ERROR: failed to connect"


def test_streaming_output_truncates_display_and_preserves_raw(tmp_path: Path) -> None:
    raw_output = "line1\nline2\nline3\nline4\n"
    condenser = OutputCondenser(max_bytes=20, max_lines=2)
    display = condenser.condense(raw_output)
    assert "truncated" in display

    config = Config()
    config.desktop_ops.enabled = True
    config.workspace.root = tmp_path / "workspaces"
    app = Aries(config)
    app.workspace.new("demo")

    controller = DesktopOpsController(app, mode="commander")
    output_path = app.workspace.current.artifact_dir / "process.log"
    handle = ProcessHandle(
        process_id="proc-1",
        started_at=datetime.now(),
        last_output_at=datetime.now(),
        raw_output_path=output_path,
    )
    controller._append_process_output(handle, raw_output)
    assert output_path.read_text(encoding="utf-8").startswith(raw_output)
