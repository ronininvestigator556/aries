"""
Custom exceptions for Aries.

All exceptions inherit from AriesError for easy catching.
"""


class AriesError(Exception):
    """Base exception for all Aries errors."""
    pass


class ConfigError(AriesError):
    """Configuration-related errors."""
    pass


class OllamaError(AriesError):
    """Ollama communication errors."""
    pass


class OllamaConnectionError(OllamaError):
    """Failed to connect to Ollama server."""
    pass


class OllamaModelError(OllamaError):
    """Model-related errors (not found, failed to load)."""
    pass


class ToolError(AriesError):
    """Tool execution errors."""
    pass


class FileToolError(ToolError):
    """File operation errors."""
    pass


class ShellToolError(ToolError):
    """Shell command execution errors."""
    pass


class SearchToolError(ToolError):
    """Web search errors."""
    pass


class RAGError(AriesError):
    """RAG-related errors."""
    pass


class IndexError(RAGError):
    """Index creation or loading errors."""
    pass


class EmbeddingError(RAGError):
    """Embedding generation errors."""
    pass


class DocumentLoadError(RAGError):
    """Document loading/parsing errors."""
    pass


class CommandError(AriesError):
    """Command parsing or execution errors."""
    pass


class InvalidCommandError(CommandError):
    """Invalid or unknown command."""
    pass


class CommandArgumentError(CommandError):
    """Invalid command arguments."""
    pass
