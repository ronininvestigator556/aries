"""Windows-focused end-to-end smoke checks for builtin Desktop Ops."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from aries.core.desktop_ops import DesktopOpsController, DesktopRisk, RunContext
from aries.core.message import ToolCall
from aries.core.workspace import resolve_and_validate_path
from aries.tools.base import ToolResult

SMOKE_ALLOWLIST = {
    "builtin:fs:list_dir",
    "builtin:fs:write_text",
    "builtin:fs:read_text",
    "builtin:shell:run",
    "builtin:web:search",
    "builtin:web:fetch",
    "builtin:web:extract",
}


@dataclass
class SmokeCheck:
    name: str
    success: bool
    detail: str
    hint: str | None = None


class SmokeDesktopOpsController(DesktopOpsController):
    """Desktop Ops controller with smoke-specific auto-approvals."""

    def __init__(
        self,
        app: Any,
        *,
        allowed_tool_ids: Iterable[str],
        mode: str | None = None,
        summary_format: str | None = None,
    ) -> None:
        super().__init__(app, mode=mode, summary_format=summary_format)
        self._smoke_allowlist = {str(tool_id) for tool_id in allowed_tool_ids}

    async def _check_approval(
        self,
        context: RunContext,
        risk: DesktopRisk,
        tool: Any,
        args: dict[str, Any],
    ) -> tuple[bool, str, list[Path] | None]:
        tool_id = getattr(tool, "qualified_id", tool.name)
        allowed_paths = context.allowed_roots

        if self._requires_path_override(context, tool, args):
            context.audit_log.append(
                {
                    "event": "smoke_auto_approval_blocked",
                    "tool": tool_id,
                    "risk": risk.value,
                    "reason": "path_outside_workspace",
                }
            )
            return False, "path_outside_workspace", None

        if not self._requires_approval(risk, tool, args):
            return True, "auto", allowed_paths

        if tool_id in self._smoke_allowlist:
            context.audit_log.append(
                {
                    "event": "smoke_auto_approval",
                    "tool": tool_id,
                    "risk": risk.value,
                    "reason": "smoke_allowlist",
                }
            )
            return True, "smoke_auto", allowed_paths

        context.audit_log.append(
            {
                "event": "smoke_auto_approval_blocked",
                "tool": tool_id,
                "risk": risk.value,
                "reason": "tool_not_allowlisted",
            }
        )
        return False, "smoke_requires_manual_approval", allowed_paths


class SmokeRunner:
    """Execute Desktop Ops smoke checks with deterministic tooling."""

    def __init__(self, app: Any) -> None:
        self.app = app
        self.controller = SmokeDesktopOpsController(
            app,
            allowed_tool_ids=SMOKE_ALLOWLIST,
            mode="commander",
        )

    async def run(self) -> int:
        checks: list[SmokeCheck] = []
        preflight_error = self._preflight_config()
        if preflight_error:
            for name in ("FS", "SHELL", "WEB", "ARTIFACTS"):
                checks.append(
                    SmokeCheck(
                        name=name,
                        success=False,
                        detail=preflight_error,
                        hint="Enable providers.builtin and rerun the smoke test.",
                    )
                )
            self._print_summary(checks)
            return 1

        workspace = self._ensure_workspace("smoke")
        context = self.controller._build_context("aries_smoke")
        content = "aries_smoke_ok"
        try:
            root = self._resolve_smoke_root(context)
            file_path = root / "aries_smoke_test.txt"
            fs_check = await self._run_fs_check(context, root, file_path, content)
        except Exception as exc:
            fs_check = SmokeCheck(
                name="FS",
                success=False,
                detail=str(exc),
                hint="Check desktop_ops.allowed_roots in config.yaml.",
            )
        checks.append(fs_check)

        shell_check = await self._run_shell_check(context)
        checks.append(shell_check)

        web_check = await self._run_web_check(context)
        checks.append(web_check)

        audit_log_path = self.controller._write_audit_log(context)
        artifacts_check = self._check_artifacts(workspace, audit_log_path)
        checks.append(artifacts_check)

        self._print_summary(checks)
        return 0 if all(check.success for check in checks) else 1

    def _preflight_config(self) -> str | None:
        providers = getattr(self.app.config, "providers", None)
        builtin_enabled = bool(getattr(getattr(providers, "builtin", None), "enabled", False))
        if not builtin_enabled:
            return "Builtin provider disabled"
        return None

    def _ensure_workspace(self, name: str) -> Any:
        try:
            return self.app.workspace.open(name)
        except FileNotFoundError:
            return self.app.workspace.new(name)

    def _resolve_smoke_root(self, context: RunContext) -> Path:
        allowed_roots = list(self.app.config.desktop_ops.allowed_roots or [])
        if not allowed_roots:
            raise RuntimeError("desktop_ops.allowed_roots is empty")
        root = Path(allowed_roots[0]).expanduser()
        if not root.is_absolute():
            root = (Path.cwd() / root).resolve()
        root = resolve_and_validate_path(
            root,
            workspace=self.app.workspace.current,
            allowed_paths=context.allowed_roots,
            denied_paths=getattr(self.app.tool_policy, "denied_paths", None),
        )
        if not root.exists():
            raise RuntimeError(
                f"Allowed root does not exist: {root}. Update desktop_ops.allowed_roots."
            )
        if not root.is_dir():
            raise RuntimeError(
                f"Allowed root is not a directory: {root}. Update desktop_ops.allowed_roots."
            )
        return root

    async def _run_fs_check(
        self,
        context: RunContext,
        root: Path,
        file_path: Path,
        content: str,
    ) -> SmokeCheck:
        list_result = await self._execute_tool(
            context,
            "builtin:fs:list_dir",
            {"path": str(root), "recursive": False, "max_entries": 50},
        )
        if not list_result.success:
            return SmokeCheck(
                name="FS",
                success=False,
                detail=list_result.error or "List directory failed",
                hint="Check desktop_ops.allowed_roots and tools.allowed_paths in config.yaml.",
            )

        write_result = await self._execute_tool(
            context,
            "builtin:fs:write_text",
            {"path": str(file_path), "content": content, "overwrite": True},
        )
        if not write_result.success:
            return SmokeCheck(
                name="FS",
                success=False,
                detail=write_result.error or "Write file failed",
                hint="Check file permissions under desktop_ops.allowed_roots.",
            )

        read_result = await self._execute_tool(
            context,
            "builtin:fs:read_text",
            {"path": str(file_path)},
        )
        if not read_result.success:
            return SmokeCheck(
                name="FS",
                success=False,
                detail=read_result.error or "Read file failed",
                hint="Check file permissions and desktop_ops.allowed_roots.",
            )

        if (read_result.content or "").strip() != content:
            return SmokeCheck(
                name="FS",
                success=False,
                detail="Readback content mismatch",
                hint="Verify filesystem tools return consistent content.",
            )

        return SmokeCheck(name="FS", success=True, detail="Filesystem tools OK")

    async def _run_shell_check(self, context: RunContext) -> SmokeCheck:
        run_result = await self._execute_tool(
            context,
            "builtin:shell:run",
            {"argv": [sys.executable, "-c", "print('aries_smoke_ok')"]},
        )
        if not run_result.success:
            return SmokeCheck(
                name="SHELL",
                success=False,
                detail=run_result.error or "Shell command failed",
                hint="Ensure tools.allow_shell is true and Python is available on PATH.",
            )

        payload = _parse_tool_json(run_result.content)
        stdout = payload.get("data", {}).get("stdout", "") if payload else ""
        if "aries_smoke_ok" not in stdout:
            return SmokeCheck(
                name="SHELL",
                success=False,
                detail="Shell output missing expected marker",
                hint="Check builtin shell tool output and encoding.",
            )

        return SmokeCheck(name="SHELL", success=True, detail="Shell tool OK")

    async def _run_web_check(self, context: RunContext) -> SmokeCheck:
        search_result = await self._execute_tool(
            context,
            "builtin:web:search",
            {"query": "example.com", "top_k": 1},
        )
        if not search_result.success:
            return SmokeCheck(
                name="WEB",
                success=False,
                detail=search_result.error or "Web search failed",
                hint="SearXNG unreachable: check search.searxng_url and that the service is running.",
            )

        results = (search_result.metadata or {}).get("results")
        if not results:
            payload = _parse_tool_json(search_result.content)
            results = (payload.get("data", {}) if payload else {}).get("results")
        if not results:
            return SmokeCheck(
                name="WEB",
                success=False,
                detail="No search results returned",
                hint="Check SearXNG index or try a different query.",
            )

        url = str(results[0].get("url") or "https://example.com")
        fetch_result = await self._execute_tool(
            context,
            "builtin:web:fetch",
            {"url": url, "timeout_seconds": 10, "max_bytes": 200000},
        )
        if not fetch_result.success:
            return SmokeCheck(
                name="WEB",
                success=False,
                detail=fetch_result.error or "Web fetch failed",
                hint="Check network access and the target URL.",
            )

        artifact_ref = (fetch_result.metadata or {}).get("artifact_ref")
        if not artifact_ref:
            payload = _parse_tool_json(fetch_result.content)
            artifact_ref = (payload.get("data", {}) if payload else {}).get("artifact_ref")
        if not artifact_ref:
            return SmokeCheck(
                name="WEB",
                success=False,
                detail="Fetch did not return an artifact reference",
                hint="Verify builtin web fetch tool writes artifacts.",
            )

        extract_result = await self._execute_tool(
            context,
            "builtin:web:extract",
            {"artifact_ref": artifact_ref, "mode": "text"},
        )
        if not extract_result.success:
            return SmokeCheck(
                name="WEB",
                success=False,
                detail=extract_result.error or "Web extract failed",
                hint="Ensure fetched content is HTML and extract settings are valid.",
            )

        text = (extract_result.metadata or {}).get("text")
        if not text:
            payload = _parse_tool_json(extract_result.content)
            text = (payload.get("data", {}) if payload else {}).get("text")
        if not text:
            return SmokeCheck(
                name="WEB",
                success=False,
                detail="Extracted text was empty",
                hint="Check extract_max_chars and source HTML content.",
            )

        return SmokeCheck(name="WEB", success=True, detail="Web tools OK")

    def _check_artifacts(self, workspace: Any, audit_log_path: Path | None) -> SmokeCheck:
        if not workspace or not self.app.workspace.artifacts:
            return SmokeCheck(
                name="ARTIFACTS",
                success=False,
                detail="Workspace artifacts registry unavailable",
                hint="Ensure workspace is initialized and artifacts directory is writable.",
            )

        artifact_dir = Path(workspace.artifact_dir)
        manifest_records = self.app.workspace.artifacts.all()
        has_artifact = False
        for record in manifest_records:
            path = record.get("path")
            if not path:
                continue
            try:
                resolved = Path(path).resolve()
            except Exception:
                continue
            if resolved.is_relative_to(artifact_dir.resolve()):
                has_artifact = True
                break
        audit_ok = bool(audit_log_path and audit_log_path.exists())

        if not has_artifact:
            return SmokeCheck(
                name="ARTIFACTS",
                success=False,
                detail="No artifacts stored under workspace artifacts directory",
                hint="Ensure web fetch or filesystem tools emit artifacts.",
            )
        if not audit_ok:
            return SmokeCheck(
                name="ARTIFACTS",
                success=False,
                detail="Desktop Ops audit log missing",
                hint="Check workspace artifact directory permissions.",
            )

        return SmokeCheck(name="ARTIFACTS", success=True, detail="Artifacts and audit logs OK")

    async def _execute_tool(
        self,
        context: RunContext,
        tool_name: str,
        args: dict[str, Any],
    ) -> ToolResult:
        tool_id, tool, error = self.app._resolve_tool_reference(tool_name)
        if tool is None or tool_id is None:
            return ToolResult(False, "", error=error or f"Tool unavailable: {tool_name}")
        call = ToolCall(
            id=f"smoke:{tool_name}",
            name=tool_id.qualified,
            arguments=args,
        )
        result, _, _ = await self.controller._execute_tool_call_with_policy(
            context,
            tool,
            tool_id,
            call,
        )
        return result

    def _print_summary(self, checks: list[SmokeCheck]) -> None:
        print("\nAries Smoke Test")
        print("-----------------")
        for check in checks:
            status = "PASS" if check.success else "FAIL"
            line = f"{check.name}: {status}"
            if not check.success and check.detail:
                line = f"{line} - {check.detail}"
            print(line)
            if not check.success and check.hint:
                print(f"  Hint: {check.hint}")


async def run_smoke(app: Any) -> int:
    """Run the smoke test against a configured Aries app."""
    runner = SmokeRunner(app)
    app.config.tools.allow_shell = True
    app.config.tools.allow_network = True
    app.config.tools.confirmation_required = False
    return await runner.run()


def _parse_tool_json(payload: str | None) -> dict[str, Any]:
    if not payload:
        return {}
    try:
        data = json.loads(payload)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}
