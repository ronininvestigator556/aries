"""
Palette command for Aries.
"""

from typing import TYPE_CHECKING

from aries.commands.base import BaseCommand
from aries.ui.palette import show_palette_prompt

if TYPE_CHECKING:
    from aries.cli import Aries


class PaletteCommand(BaseCommand):
    name = "palette"
    description = "Open command palette for quick access to commands and artifacts"
    usage = ""

    async def execute(self, app: "Aries", args: str) -> None:
        """Open the command palette."""
        from aries.commands import get_all_commands  # Avoid circular import
        
        items = {}
        
        # 1. Commands
        commands = get_all_commands()
        for cmd, desc in commands.items():
            label = f"Command: /{cmd}"
            if desc:
                label += f" - {desc}"
            items[label] = f"/{cmd}"
            
        # 2. Artifacts
        if app.workspace.artifacts:
            # Show recent artifacts first (reverse order)
            artifacts = list(reversed(app.workspace.artifacts.all()))[:50]
            for art in artifacts:
                path = art.get('path', 'unknown')
                name = art.get('name', 'unnamed')
                art_id = art.get('hash', '')[:8]
                type_ = art.get('type') or 'file'
                
                label = f"Artifact: {name} ({type_}) [{art_id}]"
                items[label] = f"/artifact open {art_id}"
        
        # 3. Workflows (Placeholder if implemented later)
        
        selection = await show_palette_prompt(items)
        if selection:
            app.next_input_default = selection
