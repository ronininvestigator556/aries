"""
Configuration management for Aries.

Uses Pydantic for type-safe configuration with YAML file support.
"""

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class OllamaConfig(BaseModel):
    """Ollama connection and model settings."""
    
    host: str = "http://localhost:11434"
    default_model: str = "llama3.2"
    embedding_model: str = "nomic-embed-text"
    timeout: int = Field(default=120, ge=1, description="Request timeout in seconds")


class SearchConfig(BaseModel):
    """SearXNG web search settings."""
    
    searxng_url: str = "http://localhost:8080"
    default_results: int = Field(default=5, ge=1, le=20)
    timeout: int = Field(default=30, ge=1)


class WorkspaceConfig(BaseModel):
    """Workspace persistence settings."""

    root: Path = Path("./workspaces")
    default: str | None = None
    persist_by_default: bool = False
    transcript_dirname: str = "transcripts"
    artifact_dirname: str = "artifacts"
    indexes_dirname: str = "indexes"
    manifest_name: str = "workspace.json"


class ProfilesConfig(BaseModel):
    """Prompt/profile settings."""

    directory: Path = Path("./profiles")
    default: str = "default"


class RAGConfig(BaseModel):
    """RAG (Retrieval Augmented Generation) settings."""
    
    chunk_size: int = Field(default=500, ge=100, le=2000)
    chunk_overlap: int = Field(default=50, ge=0, le=200)
    top_k: int = Field(default=5, ge=1, le=20)
    indices_dir: Path = Path("./indices")


class UIConfig(BaseModel):
    """Terminal UI settings."""
    
    theme: str = "dark"
    stream_output: bool = True
    show_thinking: bool = False
    max_history_display: int = Field(default=50, ge=10)


class ToolsConfig(BaseModel):
    """Tool execution settings."""
    
    shell_timeout: int = Field(default=30, ge=1)
    max_file_size_mb: int = Field(default=10, ge=1)
    allowed_extensions: list[str] = Field(default_factory=lambda: ["*"])
    allowed_paths: list[Path] = Field(
        default_factory=lambda: [Path.cwd()],
        description="Paths that tools are allowed to access",
    )
    denied_paths: list[Path] = Field(default_factory=list)
    allow_shell: bool = Field(default=False, description="Whether shell execution is allowed")
    allow_network: bool = Field(default=False, description="Whether network tools are allowed")
    confirmation_required: bool = Field(
        default=True, description="Whether dangerous tools require confirmation"
    )


class ConversationConfig(BaseModel):
    """Conversation and context window settings."""
    
    max_context_tokens: int = Field(default=4096, ge=512)
    max_messages: int = Field(default=100, ge=1)
    encoding: str = "cl100k_base"


class PromptsConfig(BaseModel):
    """System prompts settings."""
    
    directory: Path = Path("./prompts")
    default: str = "default"



class Config(BaseModel):
    """Main configuration model for Aries."""
    
    ollama: OllamaConfig = Field(default_factory=OllamaConfig)
    search: SearchConfig = Field(default_factory=SearchConfig)
    workspace: WorkspaceConfig = Field(default_factory=WorkspaceConfig)
    profiles: ProfilesConfig = Field(default_factory=ProfilesConfig)
    rag: RAGConfig = Field(default_factory=RAGConfig)
    ui: UIConfig = Field(default_factory=UIConfig)
    tools: ToolsConfig = Field(default_factory=ToolsConfig)
    conversation: ConversationConfig = Field(default_factory=ConversationConfig)
    prompts: PromptsConfig = Field(default_factory=PromptsConfig)

    @classmethod
    def load(cls, path: Path | str) -> "Config":
        """Load configuration from a YAML file.
        
        Args:
            path: Path to the YAML configuration file.
            
        Returns:
            Loaded Config instance.
            
        Raises:
            FileNotFoundError: If config file doesn't exist.
            ValueError: If config file is invalid.
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {path}")
        
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        
        return cls.model_validate(data)
    
    def save(self, path: Path | str) -> None:
        """Save configuration to a YAML file.
        
        Args:
            path: Path to save the configuration to.
        """
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(path, "w", encoding="utf-8") as f:
            yaml.safe_dump(
                self.model_dump(mode="json"),
                f,
                default_flow_style=False,
                sort_keys=False,
            )


# Global config singleton
_config: Config | None = None


def get_config() -> Config:
    """Get the global configuration instance.
    
    Returns:
        The loaded Config instance.
        
    Raises:
        RuntimeError: If config hasn't been loaded yet.
    """
    if _config is None:
        raise RuntimeError("Config not loaded. Call load_config() first.")
    return _config


def load_config(path: Path | str | None = None) -> Config:
    """Load configuration from file or create default.
    
    Args:
        path: Path to config file. If None, looks for config.yaml
              in current directory or uses defaults.
              
    Returns:
        The loaded Config instance.
    """
    global _config
    
    if path is None:
        path = Path("config.yaml")
    
    path = Path(path)
    
    if path.exists():
        _config = Config.load(path)
    else:
        _config = Config()
    
    return _config


def get_default_config_yaml() -> str:
    """Generate default configuration as YAML string.
    
    Returns:
        YAML string with default configuration.
    """
    config = Config()
    return yaml.safe_dump(
        config.model_dump(mode="json"),
        default_flow_style=False,
        sort_keys=False,
    )
