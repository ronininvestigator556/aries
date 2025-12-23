"""
/rag command - Manage RAG indices.
"""

import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from aries.commands.base import BaseCommand
from aries.ui.display import display_error, display_info, display_success

if TYPE_CHECKING:
    from aries.cli import Aries


class RAGCommand(BaseCommand):
    """List, index, or select RAG indices."""

    name = "rag"
    description = "List RAG indices, index a directory, inspect retrievals"
    usage = "[list|off|<index_name>|index add <path> [name]|use <name>|drop <name>|show <handle>|last]"

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
            if len(parts) < 3 or parts[1] != "add":
                display_error("Usage: /rag index add <path> [name]")
                return
            dir_path = Path(parts[2]).expanduser()
            name = parts[3] if len(parts) > 3 else dir_path.name

            try:
                stats = await app.indexer.index_directory(dir_path, name=name)
            except Exception as exc:
                display_error(f"Indexing failed: {exc}")
                return

            display_success(
                f"Indexed {stats['documents_indexed']} documents into '{stats['name']}'"
            )
            return

        if args.startswith("use "):
            name = args.split(maxsplit=1)[1]
            try:
                await app.retriever.load_index(name)
            except Exception as exc:
                display_error(f"Failed to load index '{name}': {exc}")
                return
            app.current_rag = name
            display_success(f"RAG index set to '{name}'")
            return

        if args.startswith("drop "):
            name = args.split(maxsplit=1)[1]
            target = Path(app.indexer.config.indices_dir) / name
            if not target.exists():
                display_error(f"Index '{name}' not found.")
                return
            shutil.rmtree(target)
            display_success(f"Dropped index '{name}'.")
            if app.current_rag == name:
                app.current_rag = None
            return

        if args.startswith("show "):
            handle = args.split(maxsplit=1)[1]
            chunk = app.retriever.get_handle(handle)
            if not chunk:
                display_error(f"Handle '{handle}' not found. Use /rag last to inspect recent retrievals.")
                return
            display_info(f"[{handle}] {chunk.source}\nScore: {chunk.score}\n{chunk.content}")
            return

        if args == "last":
            handles = app.retriever.last_handles
            if not handles:
                display_info("No retrievals yet.")
                return
            display_info("Last retrieval handles:")
            for h in handles:
                display_info(f"- {h}")
            return

        # Otherwise, treat args as index name
        try:
            await app.retriever.load_index(args)
        except Exception as exc:
            display_error(f"Failed to load index '{args}': {exc}")
            return

        app.current_rag = args
        display_success(f"RAG index set to '{args}'")
