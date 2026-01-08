from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from aries.cli import Aries
from aries.config import Config
from aries.core.smoke import SMOKE_ALLOWLIST, SmokeDesktopOpsController, SmokeRunner
from aries.tools.base import ToolResult


@pytest.mark.asyncio
async def test_smoke_runner_invokes_expected_tools(tmp_path: Path) -> None:
    config = Config()
    config.workspace.root = tmp_path / "workspaces"
    config.prompts.directory = Path(__file__).resolve().parents[1] / "prompts"
    safe_root = tmp_path / "safe"
    safe_root.mkdir()
    config.desktop_ops.allowed_roots = [safe_root]

    app = Aries(config)
    runner = SmokeRunner(app)
    context = runner.controller._build_context("aries_smoke")
    file_path = safe_root / "aries_smoke_test.txt"

    called_tool_ids: list[str] = []

    async def _fake_execute_tool_call_with_policy(context, tool, tool_id, call, **kwargs):
        called_tool_ids.append(tool_id.qualified)
        if tool_id.qualified == "builtin:fs:list_dir":
            return ToolResult(True, "listing"), {}, {}
        if tool_id.qualified == "builtin:fs:write_text":
            return ToolResult(True, "Wrote", metadata={"path": str(file_path)}), {}, {}
        if tool_id.qualified == "builtin:fs:read_text":
            return ToolResult(True, "aries_smoke_ok"), {}, {}
        if tool_id.qualified == "builtin:shell:run":
            payload = json.dumps(
                {
                    "data": {
                        "exit_code": 0,
                        "stdout": "aries_smoke_ok\n",
                        "stderr": "",
                        "timed_out": False,
                    }
                }
            )
            return ToolResult(True, payload, metadata={"exit_code": 0, "timed_out": False}), {}, {}
        if tool_id.qualified == "builtin:web:search":
            payload = json.dumps(
                {
                    "data": {
                        "query": "example.com",
                        "results": [{"url": "https://example.com"}],
                    }
                }
            )
            return ToolResult(
                True,
                payload,
                metadata={"results": [{"url": "https://example.com"}], "result_count": 1},
            ), {}, {}
        if tool_id.qualified == "builtin:web:fetch":
            payload = json.dumps({"data": {"artifact_ref": str(tmp_path / "artifact.html")}})
            return ToolResult(
                True,
                payload,
                metadata={"artifact_ref": str(tmp_path / "artifact.html")},
            ), {}, {}
        if tool_id.qualified == "builtin:web:extract":
            payload = json.dumps({"data": {"text": "Example Domain"}})
            return ToolResult(True, payload, metadata={"text": "Example Domain"}), {}, {}
        return ToolResult(False, "", error="unexpected tool"), {}, {}

    runner.controller._execute_tool_call_with_policy = _fake_execute_tool_call_with_policy

    fs_result = await runner._run_fs_check(context, safe_root, file_path, "aries_smoke_ok")
    shell_result = await runner._run_shell_check(context)
    web_result = await runner._run_web_check(context)

    assert fs_result.success
    assert shell_result.success
    assert web_result.success

    assert called_tool_ids == [
        "builtin:fs:list_dir",
        "builtin:fs:write_text",
        "builtin:fs:read_text",
        "builtin:shell:run",
        "builtin:web:search",
        "builtin:web:fetch",
        "builtin:web:extract",
    ]


@pytest.mark.asyncio
async def test_smoke_auto_approval_allowlist(tmp_path: Path) -> None:
    config = Config()
    config.workspace.root = tmp_path / "workspaces"
    config.prompts.directory = Path(__file__).resolve().parents[1] / "prompts"
    config.desktop_ops.allowed_roots = [tmp_path]

    app = Aries(config)
    controller = SmokeDesktopOpsController(app, allowed_tool_ids=SMOKE_ALLOWLIST, mode="commander")
    context = controller._build_context("aries_smoke")

    tool_id, tool, error = app._resolve_tool_reference("builtin:shell:run")
    assert error is None
    args = {"argv": [sys.executable, "-c", "print('ok')"]}
    risk = controller._classify_risk(tool, args)
    approved, reason, _ = await controller._check_approval(context, risk, tool, args)
    assert approved
    assert reason == "smoke_auto"

    tool_id, tool, error = app._resolve_tool_reference("builtin:shell:start")
    assert error is None
    args = {"argv": [sys.executable, "-c", "print('ok')"]}
    risk = controller._classify_risk(tool, args)
    approved, reason, _ = await controller._check_approval(context, risk, tool, args)
    assert not approved
    assert reason == "smoke_requires_manual_approval"
