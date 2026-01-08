from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

from aries.config import DesktopOpsProcessPollConfig
from aries.tools.builtin_shell import (
    BuiltinShellKillTool,
    BuiltinShellPollTool,
    BuiltinShellRunTool,
    BuiltinShellStartTool,
)


@pytest.mark.anyio
async def test_start_poll_kill_lifecycle(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    start_tool = BuiltinShellStartTool()
    poll_tool = BuiltinShellPollTool()
    kill_tool = BuiltinShellKillTool()

    argv = [
        sys.executable,
        "-c",
        "import time; print('hello', flush=True); time.sleep(0.2); print('done', flush=True); time.sleep(2)",
    ]
    start_result = await start_tool.execute(argv=argv, workspace=workspace)
    assert start_result.success
    payload = json.loads(start_result.content)
    process_id = payload["data"]["process_id"]

    poll_payload: dict[str, object] | None = None
    for _ in range(5):
        await asyncio.sleep(0.1)
        poll_result = await poll_tool.execute(
            process_id=process_id,
            workspace=workspace,
            process_poll=DesktopOpsProcessPollConfig(max_idle_seconds=5),
        )
        poll_payload = json.loads(poll_result.content)
        if "hello" in poll_payload["data"]["stdout_tail"]:
            break

    assert poll_payload is not None
    assert poll_payload["data"]["running"] is True
    assert "hello" in poll_payload["data"]["stdout_tail"]

    kill_result = await kill_tool.execute(process_id=process_id)
    kill_payload = json.loads(kill_result.content)
    assert kill_payload["data"]["killed"] is True


@pytest.mark.anyio
async def test_poll_truncates_tails(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    start_tool = BuiltinShellStartTool()
    poll_tool = BuiltinShellPollTool()

    argv = [sys.executable, "-c", "print('x' * 50, end='')"]
    start_result = await start_tool.execute(argv=argv, workspace=workspace)
    payload = json.loads(start_result.content)
    process_id = payload["data"]["process_id"]

    poll_payload: dict[str, object] | None = None
    for _ in range(5):
        await asyncio.sleep(0.05)
        poll_result = await poll_tool.execute(
            process_id=process_id, max_bytes=10, workspace=workspace
        )
        poll_payload = json.loads(poll_result.content)
        if poll_payload["data"]["stdout_tail"]:
            break

    assert poll_payload is not None
    assert poll_payload["meta"]["truncated_stdout"] is True
    assert len(poll_payload["data"]["stdout_tail"]) <= 10


@pytest.mark.anyio
async def test_run_merges_env_and_preserves_path(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    run_tool = BuiltinShellRunTool()
    argv = [
        sys.executable,
        "-c",
        "import os; print('PATH' in os.environ); print(os.environ.get('ARIES_TEST_ENV', ''))",
    ]
    result = await run_tool.execute(
        argv=argv,
        cwd=str(workspace),
        env={"ARIES_TEST_ENV": "ok"},
        workspace=workspace,
    )
    payload = json.loads(result.content)
    stdout = payload["data"]["stdout"]

    assert "True" in stdout
    assert "ok" in stdout


@pytest.mark.anyio
async def test_run_defaults_to_workspace_cwd(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    run_tool = BuiltinShellRunTool()
    argv = [sys.executable, "-c", "import os; print(os.getcwd())"]
    result = await run_tool.execute(argv=argv, workspace=workspace)
    payload = json.loads(result.content)

    assert payload["data"]["stdout"].strip() == str(workspace)


@pytest.mark.anyio
async def test_run_rejects_cwd_outside_allowed_paths(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()

    run_tool = BuiltinShellRunTool()
    result = await run_tool.execute(
        argv=[sys.executable, "-c", "print('nope')"],
        cwd=str(outside),
        workspace=workspace,
        allowed_paths=[workspace],
    )

    assert result.success is False
    assert "Path outside allowed locations" in (result.error or "")
