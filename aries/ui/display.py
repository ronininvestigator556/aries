"""
Display utilities for terminal output.
"""

from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich.markdown import Markdown

from aries.config import Config
from aries import __version__


console = Console()


def display_welcome(config: Config) -> None:
    """Display welcome message.
    
    Args:
        config: Application configuration.
    """
    title = Text()
    title.append("★ ", style="yellow")
    title.append("ARIES", style="bold cyan")
    title.append(" ★", style="yellow")
    
    welcome_text = Text()
    welcome_text.append(f"AI Research & Investigation Enhancement System v{__version__}\n\n", style="dim")
    welcome_text.append(f"Model: ", style="dim")
    welcome_text.append(f"{config.ollama.default_model}\n", style="green")
    welcome_text.append(f"Ollama: ", style="dim")
    welcome_text.append(f"{config.ollama.host}\n\n", style="blue")
    welcome_text.append("Type ", style="dim")
    welcome_text.append("/help", style="yellow")
    welcome_text.append(" for commands, ", style="dim")
    welcome_text.append("/exit", style="yellow")
    welcome_text.append(" to quit.", style="dim")
    
    panel = Panel(
        welcome_text,
        title=title,
        border_style="cyan",
        padding=(1, 2),
    )
    console.print(panel)
    console.print()


def display_error(message: str) -> None:
    """Display an error message.
    
    Args:
        message: Error message to display.
    """
    console.print(f"[bold red]Error:[/bold red] {message}")


def display_response(content: str, stream: bool = False) -> None:
    """Display an assistant response.
    
    Args:
        content: Response content.
        stream: Whether this is a streaming response.
    """
    if not stream:
        console.print(Markdown(content))


def display_info(message: str) -> None:
    """Display an info message.
    
    Args:
        message: Info message to display.
    """
    console.print(f"[cyan]ℹ[/cyan] {message}")


def display_success(message: str) -> None:
    """Display a success message.
    
    Args:
        message: Success message to display.
    """
    console.print(f"[green]✓[/green] {message}")


def display_warning(message: str) -> None:
    """Display a warning message.
    
    Args:
        message: Warning message to display.
    """
    console.print(f"[yellow]⚠[/yellow] {message}")


def display_model_list(models: list[str], current: str) -> None:
    """Display list of available models.
    
    Args:
        models: List of model names.
        current: Currently selected model.
    """
    console.print("\n[bold]Available Models:[/bold]")
    for model in models:
        if model == current or model.startswith(f"{current}:"):
            console.print(f"  [green]● {model}[/green] (active)")
        else:
            console.print(f"  ○ {model}")
    console.print()


def display_command_help(commands: dict[str, str]) -> None:
    """Display command help.
    
    Args:
        commands: Dictionary of command names to descriptions.
    """
    console.print("\n[bold]Available Commands:[/bold]\n")
    for cmd, desc in commands.items():
        console.print(f"  [yellow]/{cmd}[/yellow]  {desc}")
    console.print()
