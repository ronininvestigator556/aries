"""
Aries - AI Research & Investigation Enhancement System

A terminal-based AI assistant powered by local LLMs via Ollama,
with integrated RAG, web search, and file/shell tools.
"""

__version__ = "0.1.0"
__author__ = "Alex"

from aries.config import Config, get_config

__all__ = ["Config", "get_config", "__version__"]
