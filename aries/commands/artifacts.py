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
from aries.ui.display import display_error

if TYPE_CHECKING:
    from aries.cli import Aries

console = Console()


class ArtifactsCommand(BaseCommand):
    name = "artifacts"
    description = "Browse and inspect workspace artifacts"
    usage = "[list] [--type TYPE] [--limit N] | open <id>"

    async def execute(self, app: "Aries", args: str) -> None:
        """Execute the artifacts command."""
        args_list = args.split()
        subcmd = args_list[0] if args_list else "list"

        if subcmd == "open":
            if len(args_list) < 2:
                display_error("Usage: /artifacts open <id>")
                return
            await self._open_artifact(app, args_list[1])
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

    def _format_size(self, size: int) -> str:
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024:
                return f"{size:.1f}{unit}"
            size /= 1024
        return f"{size:.1f}TB"
