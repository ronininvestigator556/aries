"""
/rag command - Manage RAG indices.
"""

from pathlib import Path
from typing import TYPE_CHECKING

from aries.commands.base import BaseCommand
from aries.ui.display import display_error, display_info, display_success

if TYPE_CHECKING:
    from aries.cli import Aries


class RAGCommand(BaseCommand):
    """List, index, or select RAG indices."""

    name = "rag"
    description = "List RAG indices, index a directory, or select an index"
    usage = "[list|off|<index_name>|index <path> [name]]"

    async def execute(self, app: "Aries", args: str) -> None:
        args = args.strip()

        if not args or args == "list":
            indices = app.indexer.list_indices()
            if not indices:
                display_info("No indices found.")
                return

            display_info("Available indices:")
            for idx in indices:
                marker = " (active)" if app.retriever.current_index == idx else ""
                display_info(f"- {idx}{marker}")
            return

        if args == "off":
            app.retriever.unload()
            app.current_rag = None
            display_success("RAG disabled.")
            return

        if args.startswith("index "):
            parts = args.split()
            if len(parts) < 2:
                display_error("Usage: /rag index <path> [name]")
                return
            dir_path = Path(parts[1]).expanduser()
            name = parts[2] if len(parts) > 2 else dir_path.name

            try:
                stats = await app.indexer.index_directory(dir_path, name=name)
            except Exception as exc:
                display_error(f"Indexing failed: {exc}")
                return

            display_success(
                f"Indexed {stats['documents_indexed']} documents into '{stats['name']}'"
            )
            return

        # Otherwise, treat args as index name
        try:
            await app.retriever.load_index(args)
        except Exception as exc:
            display_error(f"Failed to load index '{args}': {exc}")
            return

        app.current_rag = args
        display_success(f"RAG index set to '{args}'")
