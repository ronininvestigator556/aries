"""
/model command - List and switch models.
"""

from typing import TYPE_CHECKING

from rich.console import Console

from aries.commands.base import BaseCommand
from aries.ui.display import display_model_list, display_error, display_success

if TYPE_CHECKING:
    from aries.cli import Aries


console = Console()


class ModelCommand(BaseCommand):
    """List available models or switch to a different model."""
    
    name = "model"
    description = "List available models or switch to a specified model"
    usage = "list | <model_name> | use <model_name> | set <model_name> | switch <model_name>"
    
    async def execute(self, app: "Aries", args: str) -> None:
        """Execute model command.
        
        Args:
            app: Aries application instance.
            args: Optional model name to switch to.
        """
        args = args.strip()
        
        if not args:
            console.print(f"\n{self.get_help()}\n")
            return

        if args == "list":
            # List models
            models = await app.ollama.get_model_names()
            if not models:
                display_error("No models found. Run 'ollama pull <model>' to download one.")
                return
            display_model_list(models, app.current_model)
        
        elif args.startswith("pull "):
            # Pull a model
            model_name = args[5:].strip()
            if not model_name:
                display_error("Usage: /model pull <model_name>")
                return
            
            console.print(f"Pulling model: {model_name}")
            try:
                async for progress in app.ollama.pull_model(model_name):
                    status = progress.get("status", "")
                    if "completed" in progress:
                        total = progress.get("total", 0)
                        completed = progress.get("completed", 0)
                        if total > 0:
                            pct = (completed / total) * 100
                            console.print(f"\r{status}: {pct:.1f}%", end="")
                    else:
                        console.print(f"\r{status}", end="")
                console.print("\n")
                display_success(f"Model '{model_name}' pulled successfully")
            except Exception as e:
                display_error(f"Failed to pull model: {e}")
        
        else:
            # Switch model
            parts = args.split()
            if parts[0] in {"use", "set", "switch"}:
                model_name = " ".join(parts[1:]).strip()
                if not model_name:
                    display_error(f"Usage: /model {parts[0]} <model_name>")
                    return
            else:
                model_name = args
            if await app.ollama.model_exists(model_name):
                app.current_model = model_name
                display_success(f"Switched to model: {model_name}")
            else:
                display_error(f"Model not found: {model_name}\nUse /model list to see available models.")

    def get_help(self) -> str:
        return (
            "/model commands:\n"
            "  /model list\n"
            "  /model <model_name>\n"
            "  /model use <model_name>\n"
            "  /model set <model_name>\n"
            "  /model switch <model_name>\n\n"
            "Examples:\n"
            "  /model list\n"
            "  /model llama3.2:latest\n"
            "  /model use llama3.1:latest\n"
            "  /model set mistral:latest\n\n"
            "List available models or switch to a specified model."
        )
