"""
Command to manage and inspect artifacts.
"""

import argparse
from typing import TYPE_CHECKING, Any

from rich.console import Console
from rich.table import Table
from rich.text import Text
from rich.syntax import Syntax

from aries.commands.base import BaseCommand
from aries.core.run_manager import RunManager
from aries.ui.display import display_error, display_info

if TYPE_CHECKING:
    from aries.cli import Aries

console = Console()


class ArtifactsCommand(BaseCommand):
    name = "artifacts"
    description = "Browse and inspect workspace artifacts"
    usage = "[list] [--type TYPE] [--limit N] | open <id> | run [run_id]"

    async def execute(self, app: "Aries", args: str) -> None:
        """Execute the artifacts command."""
        args_list = args.split()
        subcmd = args_list[0] if args_list else "list"

        if subcmd == "open":
            if len(args_list) < 2:
                display_error("Usage: /artifacts open <id>")
                return
            await self._open_artifact(app, args_list[1])
        elif subcmd == "run":
            run_id = args_list[1] if len(args_list) > 1 else None
            await self._list_run_artifacts(app, run_id)
        elif subcmd == "list":
            self._list_artifacts(app, args_list[1:])
        else:
            # Default to list if unknown subcommand, but check if it's flags
            if subcmd.startswith("-"):
                self._list_artifacts(app, args_list)
            else:
                self._list_artifacts(app, args_list)

    def _list_artifacts(self, app: "Aries", args: list[str]) -> None:
        parser = argparse.ArgumentParser(exit_on_error=False, add_help=False)
        parser.add_argument("--type", help="Filter by type")
        parser.add_argument("--contains", help="Filter by name/path")
        parser.add_argument("--limit", type=int, default=20, help="Max items to show")
        
        try:
            parsed, unknown = parser.parse_known_args(args)
        except argparse.ArgumentError as e:
            display_error(str(e))
            return

        if not app.workspace.artifacts:
            console.print("[yellow]No artifacts registry in current workspace.[/yellow]")
            return

        artifacts = app.workspace.artifacts.all()
        # Sort by creation time desc (assuming logic, but created_at is string ISO)
        artifacts.sort(key=lambda x: x.get("created_at", ""), reverse=True)

        # Filter
        filtered = []
        for art in artifacts:
            if parsed.type and parsed.type.lower() not in (art.get("type") or "").lower():
                continue
            if parsed.contains:
                query = parsed.contains.lower()
                if query not in art.get("name", "").lower() and query not in art.get("path", "").lower():
                    continue
            filtered.append(art)

        displayed = filtered[:parsed.limit]

        table = Table(title=f"Artifacts ({len(displayed)}/{len(filtered)})")
        table.add_column("ID", style="cyan", no_wrap=True)
        table.add_column("Name", style="bold")
        table.add_column("Type", style="magenta")
        table.add_column("Size", justify="right")
        table.add_column("Path", style="dim")

        for art in displayed:
            art_id = art.get("hash", "")[:8]
            size = self._format_size(art.get("size_bytes", 0))
            table.add_row(
                art_id,
                art.get("name", "unnamed"),
                art.get("type") or "file",
                size,
                str(art.get("path"))
            )

        console.print(table)

    async def _open_artifact(self, app: "Aries", art_id: str) -> None:
        if not app.workspace.artifacts:
            display_error("No artifacts registry.")
            return

        found = None
        for art in app.workspace.artifacts.all():
            if art.get("hash", "").startswith(art_id):
                found = art
                break
        
        if not found:
            display_error(f"Artifact not found: {art_id}")
            return

        path_str = found.get("path")
        console.print(f"[bold]Artifact:[/bold] {found.get('name')}")
        console.print(f"[dim]Path: {path_str}[/dim]")
        
        try:
            from pathlib import Path
            path = Path(path_str)
            if not path.exists():
                display_error("File not found on disk.")
                return
            
            # Preview if text
            mime = found.get("mime_type", "")
            if "text" in mime or path.suffix in {".txt", ".md", ".py", ".json", ".yaml", ".yml", ".log"}:
                content = path.read_text(encoding="utf-8", errors="replace")
                preview = "\n".join(content.splitlines()[:20])
                if len(content.splitlines()) > 20:
                    preview += "\n... (truncated)"
                
                console.print(Syntax(preview, path.suffix.lstrip(".") or "text", theme="monokai", line_numbers=True))
            else:
                console.print("[italic]Binary file, preview unavailable.[/italic]")

        except Exception as e:
            display_error(f"Failed to read artifact: {e}")

    async def _list_run_artifacts(self, app: "Aries", run_id: str | None) -> None:
        """List artifacts grouped by step for a run."""
        # Initialize run manager if needed
        if not hasattr(app, "run_manager"):
            workspace_root = app.workspace.current.root if app.workspace.current else None
            app.run_manager = RunManager(workspace_root)

        # Get run
        if run_id:
            run = app.run_manager.load_run(run_id)
            if not run:
                display_error(f"Run '{run_id}' not found.")
                return
        elif hasattr(app, "current_run") and app.current_run:
            run = app.current_run
        else:
            display_error("No run specified and no active run.")
            return

        console.print(f"\n[bold]Artifacts for Run: {run.run_id}[/bold]")

        # Group artifacts by step
        for step in run.plan:
            result = run.get_step_result(step.step_index)
            if result and result.artifacts:
                console.print(f"\n[cyan]Step {step.step_index + 1}: {step.title}[/cyan]")
                for artifact in result.artifacts:
                    artifact_id = artifact.get("id") or artifact.get("path", "unknown")
                    artifact_name = artifact.get("name") or artifact.get("path", "unnamed")
                    console.print(f"  - {artifact_name} (ID: {artifact_id[:16] if isinstance(artifact_id, str) else str(artifact_id)[:16]})")
            elif result:
                console.print(f"\n[dim]Step {step.step_index + 1}: {step.title} - No artifacts[/dim]")

        if not any(run.get_step_result(s.step_index) and run.get_step_result(s.step_index).artifacts for s in run.plan):
            display_info("No artifacts found for this run.")

    def _format_size(self, size: int) -> str:
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024:
                return f"{size:.1f}{unit}"
            size /= 1024
        return f"{size:.1f}TB"
