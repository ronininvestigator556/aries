"""Deterministic Desktop Ops recipes."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, TYPE_CHECKING

from aries.config import DesktopOpsConfig
from aries.core.workspace import resolve_and_validate_path
from aries.exceptions import FileToolError

if TYPE_CHECKING:
    from aries.core.desktop_ops import RunContext


_RECIPE_PREFIX = "desktop.recipe."


@dataclass
class RecipeStep:
    name: str
    tool_name: str
    arguments: dict[str, Any] | Callable[[RunContext, dict[str, Any] | None], dict[str, Any]]
    description: str | None = None
    on_failure: Callable[[str], Iterable["RecipeStep"]] | None = None


@dataclass
class RecipePlan:
    name: str
    steps: list[RecipeStep]
    done_criteria: Callable[[RunContext, list[dict[str, Any]]], bool]
    summary: str | None = None


@dataclass
class RecipeMatch:
    name: str
    arguments: dict[str, Any]
    reason: str


@dataclass
class RecipeOutcome:
    success: bool
    content: str
    error: str | None = None
    artifacts: list[dict[str, Any]] = field(default_factory=list)


class DesktopRecipeRegistry:
    """Registry for deterministic Desktop Ops recipes."""

    def __init__(self, config: DesktopOpsConfig) -> None:
        self.config = config

    def definitions(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": f"{_RECIPE_PREFIX}repo_clone_open",
                    "description": "Clone a repository and open it in the workspace.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "repo_url": {"type": "string"},
                            "dest_dir": {"type": "string"},
                        },
                        "required": ["repo_url", "dest_dir"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": f"{_RECIPE_PREFIX}python_bootstrap",
                    "description": "Create a virtualenv and install dependencies.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "repo_root": {"type": "string"},
                            "python_exe": {"type": "string"},
                            "venv_dir": {"type": "string", "default": ".venv"},
                        },
                        "required": ["repo_root"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": f"{_RECIPE_PREFIX}run_tests",
                    "description": "Run tests using a deterministic command.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "repo_root": {"type": "string"},
                            "argv": {
                                "type": "array",
                                "items": {"type": "string"},
                                "default": ["pytest", "-q"],
                            },
                            "target": {"type": "string"},
                        },
                        "required": ["repo_root"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": f"{_RECIPE_PREFIX}run_git_status",
                    "description": "Run git status in the repository.",
                    "parameters": {
                        "type": "object",
                        "properties": {"repo_root": {"type": "string"}},
                        "required": ["repo_root"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": f"{_RECIPE_PREFIX}list_directory",
                    "description": "List files in a directory.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"},
                            "recursive": {"type": "boolean", "default": False},
                            "glob": {"type": "string"},
                            "max_entries": {"type": "integer", "default": 200},
                        },
                        "required": ["path"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": f"{_RECIPE_PREFIX}create_text_file",
                    "description": "Create or overwrite a text file with deterministic content.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"},
                            "content": {"type": "string"},
                        },
                        "required": ["path", "content"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": f"{_RECIPE_PREFIX}build_project",
                    "description": "Build the project using common build commands.",
                    "parameters": {
                        "type": "object",
                        "properties": {"repo_root": {"type": "string"}},
                        "required": ["repo_root"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": f"{_RECIPE_PREFIX}log_tail",
                    "description": "Start, stream, and stop a log tailing process.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "file_path": {"type": "string"},
                            "max_seconds": {"type": "number"},
                            "lines": {"type": "integer", "default": 50},
                        },
                        "required": ["file_path"],
                    },
                },
            },
        ]

    def plan(self, name: str, args: dict[str, Any], context: RunContext) -> RecipePlan:
        if name == "repo_clone_open":
            return self._plan_repo_clone_open(args, context)
        if name == "python_bootstrap":
            return self._plan_python_bootstrap(args, context)
        if name == "run_tests":
            return self._plan_run_tests(args, context)
        if name == "run_git_status":
            return self._plan_run_git_status(args, context)
        if name == "create_text_file":
            return self._plan_create_text_file(args, context)
        if name == "list_directory":
            return self._plan_list_directory(args, context)
        if name == "build_project":
            return self._plan_build_project(args, context)
        if name == "log_tail":
            return self._plan_log_tail(args, context)
        raise ValueError(f"Unknown recipe: {name}")

    def match_goal(self, goal: str, context: RunContext) -> RecipeMatch | None:
        normalized = goal.lower()
        repo_url = _extract_repo_url(goal)
        if "clone" in normalized and repo_url:
            dest_dir = _extract_dest_dir(goal) or _repo_name_from_url(repo_url)
            if dest_dir:
                return RecipeMatch(
                    name="repo_clone_open",
                    arguments={"repo_url": repo_url, "dest_dir": dest_dir},
                    reason="goal_mentions_clone",
                )
        if any(token in normalized for token in ("bootstrap", "venv", "virtualenv")):
            if context.repo_root:
                return RecipeMatch(
                    name="python_bootstrap",
                    arguments={"repo_root": str(context.repo_root)},
                    reason="goal_mentions_bootstrap",
                )
        file_request = _extract_file_request(goal)
        if file_request:
            path, content = file_request
            return RecipeMatch(
                name="create_text_file",
                arguments={"path": path, "content": content},
                reason="goal_mentions_file_write",
            )
        list_request = _extract_list_request(goal)
        if list_request:
            try:
                resolved = resolve_and_validate_path(
                    list_request["path"],
                    workspace=context.cwd,
                    allowed_paths=context.allowed_roots,
                )
                if not resolved.exists():
                    list_request = None
            except FileToolError:
                list_request = None
        if list_request:
            return RecipeMatch(
                name="list_directory",
                arguments=list_request,
                reason="goal_mentions_list_directory",
            )
        if context.repo_root and _mentions_tests(goal):
            return RecipeMatch(
                name="run_tests",
                arguments={"repo_root": str(context.repo_root)},
                reason="goal_mentions_tests",
            )
        if context.repo_root and _mentions_git_status(goal):
            return RecipeMatch(
                name="run_git_status",
                arguments={"repo_root": str(context.repo_root)},
                reason="goal_mentions_git_status",
            )
        if "build" in normalized and context.repo_root:
            return RecipeMatch(
                name="build_project",
                arguments={"repo_root": str(context.repo_root)},
                reason="goal_mentions_build",
            )
        log_path = _extract_log_path(goal)
        if log_path:
            return RecipeMatch(
                name="log_tail",
                arguments={"file_path": log_path},
                reason="goal_mentions_logs",
            )
        return None

    def _plan_repo_clone_open(self, args: dict[str, Any], context: RunContext) -> RecipePlan:
        repo_url = args.get("repo_url")
        dest_dir = args.get("dest_dir")
        if not repo_url or not dest_dir:
            raise ValueError("repo_url and dest_dir are required")
        dest_path = Path(dest_dir).expanduser()
        commands: list[RecipeStep] = []
        if dest_path.exists():
            commands.extend(
                [
                    RecipeStep(
                        name="fetch_updates",
                        tool_name="shell",
                        arguments={"command": f"cd {dest_dir} && git fetch --all --prune"},
                        description="Fetch latest refs for existing repository",
                    ),
                    RecipeStep(
                        name="status",
                        tool_name="shell",
                        arguments={"command": f"cd {dest_dir} && git status -sb"},
                        description="Show repository status",
                    ),
                ]
            )
        else:
            commands.extend(
                [
                    RecipeStep(
                        name="clone",
                        tool_name="shell",
                        arguments={"command": f"git clone {repo_url} {dest_dir}"},
                        description="Clone repository",
                    ),
                    RecipeStep(
                        name="status",
                        tool_name="shell",
                        arguments={"command": f"cd {dest_dir} && git status -sb"},
                        description="Show repository status",
                    ),
                ]
            )

        def done_criteria(run_context: RunContext, _: list[dict[str, Any]]) -> bool:
            repo_root = _find_repo_root(Path(dest_dir).expanduser().resolve())
            if repo_root:
                run_context.repo_root = repo_root
            return repo_root is not None

        return RecipePlan(
            name="repo_clone_open",
            steps=commands,
            done_criteria=done_criteria,
            summary="Repository cloned/opened and status captured.",
        )

    def _plan_python_bootstrap(self, args: dict[str, Any], context: RunContext) -> RecipePlan:
        repo_root = args.get("repo_root")
        if not repo_root:
            raise ValueError("repo_root is required")
        python_exe = args.get("python_exe") or "python"
        venv_dir = args.get("venv_dir") or ".venv"
        extras = _resolve_extras(self.config)
        extras_flag = f".[{','.join(sorted(extras))}]" if extras else "."
        base = f"cd {repo_root}"
        steps = [
            RecipeStep(
                name="create_venv",
                tool_name="shell",
                arguments={"command": f"{base} && {python_exe} -m venv {venv_dir}"},
                description="Create virtualenv",
            ),
            RecipeStep(
                name="upgrade_pip",
                tool_name="shell",
                arguments={
                    "command": f"{base} && . {venv_dir}/bin/activate && {python_exe} -m pip install -U pip"
                },
                description="Upgrade pip",
            ),
            RecipeStep(
                name="install_editable",
                tool_name="shell",
                arguments={
                    "command": f"{base} && . {venv_dir}/bin/activate && {python_exe} -m pip install -e '{extras_flag}'"
                },
                description="Install editable package with extras",
            ),
        ]

        def done_criteria(run_context: RunContext, _: list[dict[str, Any]]) -> bool:
            venv_path = Path(repo_root) / venv_dir
            if venv_path.exists():
                run_context.virtualenv = venv_path.name
                return True
            return False

        return RecipePlan(
            name="python_bootstrap",
            steps=steps,
            done_criteria=done_criteria,
            summary="Virtualenv created and dependencies installed.",
        )

    def _plan_run_tests(self, args: dict[str, Any], context: RunContext) -> RecipePlan:
        repo_root = args.get("repo_root")
        if not repo_root:
            raise ValueError("repo_root is required")
        argv = args.get("argv")
        if not isinstance(argv, list) or not argv:
            argv = ["pytest", "-q"]
        target = args.get("target")
        command_argv = [str(part) for part in argv]
        if target:
            command_argv.append(str(target))

        def retry_steps(output: str) -> Iterable[RecipeStep]:
            if "No module named pytest" in output or "pytest: command not found" in output:
                yield RecipeStep(
                    name="install_pytest",
                    tool_name="builtin:shell:run",
                    arguments={
                        "argv": ["python", "-m", "pip", "install", "pytest"],
                        "cwd": repo_root,
                    },
                    description="Install pytest for missing dependency",
                )
                yield RecipeStep(
                    name="rerun_tests",
                    tool_name="builtin:shell:run",
                    arguments={"argv": command_argv, "cwd": repo_root},
                    description="Re-run tests after installing pytest",
                )

        steps = [
            RecipeStep(
                name="run_tests",
                tool_name="builtin:shell:run",
                arguments={"argv": command_argv, "cwd": repo_root},
                description="Run test suite",
                on_failure=retry_steps,
            )
        ]

        def done_criteria(_: RunContext, step_results: list[dict[str, Any]]) -> bool:
            return bool(step_results and step_results[-1].get("success"))

        return RecipePlan(
            name="run_tests",
            steps=steps,
            done_criteria=done_criteria,
            summary="Tests executed.",
        )

    def _plan_run_git_status(self, args: dict[str, Any], context: RunContext) -> RecipePlan:
        repo_root = args.get("repo_root")
        if not repo_root:
            raise ValueError("repo_root is required")

        steps = [
            RecipeStep(
                name="run_git_status",
                tool_name="builtin:shell:run",
                arguments={"argv": ["git", "status"], "cwd": repo_root},
                description="Run git status",
            )
        ]

        def done_criteria(_: RunContext, step_results: list[dict[str, Any]]) -> bool:
            return bool(step_results and step_results[-1].get("success"))

        return RecipePlan(
            name="run_git_status",
            steps=steps,
            done_criteria=done_criteria,
            summary="Git status captured.",
        )

    def _plan_build_project(self, args: dict[str, Any], context: RunContext) -> RecipePlan:
        repo_root = args.get("repo_root")
        if not repo_root:
            raise ValueError("repo_root is required")
        root = Path(repo_root)
        command = _detect_build_command(root)
        steps = [
            RecipeStep(
                name="build",
                tool_name="shell",
                arguments={"command": f"cd {repo_root} && {command}"},
                description="Build project",
            )
        ]

        def done_criteria(_: RunContext, step_results: list[dict[str, Any]]) -> bool:
            return bool(step_results and step_results[-1].get("success"))

        return RecipePlan(
            name="build_project",
            steps=steps,
            done_criteria=done_criteria,
            summary=f"Build executed using `{command}`.",
        )

    def _plan_log_tail(self, args: dict[str, Any], context: RunContext) -> RecipePlan:
        file_path = args.get("file_path")
        if not file_path:
            raise ValueError("file_path is required")
        lines = int(args.get("lines") or 50)
        max_seconds = args.get("max_seconds")

        steps = [
            RecipeStep(
                name="start_tail",
                tool_name="start_process",
                arguments={"command": f"tail -n {lines} -f {file_path}"},
                description="Start tail process",
            ),
            RecipeStep(
                name="stop_tail",
                tool_name="stop_process",
                arguments=_process_id_args,
                description="Stop tail process",
            ),
        ]

        def done_criteria(_: RunContext, step_results: list[dict[str, Any]]) -> bool:
            if not step_results:
                return False
            return True

        plan = RecipePlan(
            name="log_tail",
            steps=steps,
            done_criteria=done_criteria,
            summary="Log tail captured.",
        )
        if max_seconds is not None:
            context.audit_log.append(
                {
                    "event": "recipe_hint",
                    "recipe": "log_tail",
                    "max_seconds": max_seconds,
                }
            )
        return plan

    def _plan_create_text_file(self, args: dict[str, Any], context: RunContext) -> RecipePlan:
        path = args.get("path")
        if not path:
            raise ValueError("path is required")
        content = str(args.get("content") or "")

        steps = [
            RecipeStep(
                name="write_file",
                tool_name="builtin:fs:write_text",
                arguments={"path": path, "content": content, "overwrite": True},
                description="Write text file deterministically",
            ),
        ]

        def done_criteria(_: RunContext, step_results: list[dict[str, Any]]) -> bool:
            if not step_results:
                return False
            return step_results[-1].get("success", False)

        return RecipePlan(
            name="create_text_file",
            steps=steps,
            done_criteria=done_criteria,
            summary="Text file created.",
        )

    def _plan_list_directory(self, args: dict[str, Any], context: RunContext) -> RecipePlan:
        path = args.get("path")
        if not path:
            raise ValueError("path is required")
        recursive = bool(args.get("recursive", False))
        glob = args.get("glob")
        max_entries = int(args.get("max_entries") or 200)

        steps = [
            RecipeStep(
                name="list_directory",
                tool_name="builtin:fs:list_dir",
                arguments={
                    "path": path,
                    "recursive": recursive,
                    "glob": glob,
                    "max_entries": max_entries,
                },
                description="List directory contents deterministically",
            )
        ]

        def done_criteria(_: RunContext, step_results: list[dict[str, Any]]) -> bool:
            if not step_results:
                return False
            return step_results[-1].get("success", False)

        return RecipePlan(
            name="list_directory",
            steps=steps,
            done_criteria=done_criteria,
            summary="Directory listed.",
        )


def _extract_repo_url(goal: str) -> str | None:
    match = re.search(r"(https?://\S+|git@[^\s:]+:[^\s]+)", goal)
    return match.group(1) if match else None


def _repo_name_from_url(repo_url: str) -> str | None:
    name = repo_url.rstrip("/").split("/")[-1]
    if name.endswith(".git"):
        name = name[:-4]
    return name or None


def _extract_dest_dir(goal: str) -> str | None:
    match = re.search(r"\b(?:to|into)\s+([\w./-]+)", goal, re.IGNORECASE)
    return match.group(1) if match else None


def _extract_log_path(goal: str) -> str | None:
    match = re.search(r"(/[^\s]+\.log)", goal)
    return match.group(1) if match else None


def _mentions_tests(goal: str) -> bool:
    normalized = goal.lower()
    if re.search(r"\bpytest\b", normalized):
        return True
    if re.search(r"\btest suite\b", normalized):
        return True
    if re.search(r"\b(unit|integration)\s+tests?\b", normalized):
        return True
    return bool(re.search(r"\b(run|rerun|execute)\s+(the\s+)?tests?\b", normalized))


def _mentions_git_status(goal: str) -> bool:
    return bool(re.search(r"\bgit\s+status\b", goal, re.IGNORECASE))


def _extract_file_request(goal: str) -> tuple[str, str] | None:
    if not re.search(r"\b(create|write|save)\b", goal, re.IGNORECASE):
        return None
    path = _extract_file_path(goal)
    if not path:
        return None
    content = _extract_file_content(goal) or ""
    return path, content


def _extract_list_request(goal: str) -> dict[str, Any] | None:
    if not re.search(r"\b(list|show)\b", goal, re.IGNORECASE):
        return None
    if not re.search(r"\b(files|file|directory|dir|folders?)\b", goal, re.IGNORECASE):
        return None
    path = _extract_file_path(goal)
    if not path:
        return None
    return {"path": path}


def _extract_file_path(goal: str) -> str | None:
    match = re.search(
        r"\b(?:to|at|in|into|path)\s+(\"[^\"]+\"|'[^']+'|[^\s]+)",
        goal,
        re.IGNORECASE,
    )
    if not match:
        match = re.search(
            r"\bfile\s+(?:named\s+)?(\"[^\"]+\"|'[^']+'|[^\s]+)",
            goal,
            re.IGNORECASE,
        )
    if not match:
        return None
    candidate = match.group(1).strip()
    if candidate.startswith(("\"", "'")) and candidate.endswith(("\"", "'")):
        candidate = candidate[1:-1]
    return candidate


def _extract_file_content(goal: str) -> str | None:
    match = re.search(
        r"\b(?:content|text)\b\s*[:=]?\s*(\"[^\"]+\"|'[^']+')",
        goal,
        re.IGNORECASE,
    )
    if match:
        content = match.group(1)
        if content.startswith(("\"", "'")) and content.endswith(("\"", "'")):
            return content[1:-1]
        return content
    return None


def _detect_build_command(root: Path) -> str:
    if (root / "pyproject.toml").exists():
        return "python -m build"
    if (root / "package.json").exists():
        return "npm run build"
    if (root / "Makefile").exists():
        return "make build"
    if (root / "CMakeLists.txt").exists():
        return "cmake --build build"
    return "make"


def _resolve_extras(config: DesktopOpsConfig) -> set[str]:
    extras = set(config.python_bootstrap_extras)
    if "all" in extras:
        return {"all"}
    return {extra for extra in extras if extra in {"dev", "rag"}}


def _find_repo_root(path: Path) -> Path | None:
    current = path
    while current != current.parent:
        if (current / ".git").exists():
            return current
        current = current.parent
    return None


def _process_id_args(context: RunContext, last_result: dict[str, Any] | None) -> dict[str, Any]:
    metadata = last_result.get("metadata", {}) if last_result else {}
    process_id = metadata.get("process_id") or metadata.get("session_id") or metadata.get("pid")
    if not process_id:
        return {}
    return {"process_id": str(process_id)}


def recipe_prefix() -> str:
    return _RECIPE_PREFIX


__all__ = [
    "DesktopRecipeRegistry",
    "RecipeMatch",
    "RecipeOutcome",
    "RecipePlan",
    "RecipeStep",
    "recipe_prefix",
]
