"""Configuration management for the dump debugger."""

from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # LLM Configuration
    llm_provider: Literal["openai", "anthropic", "azure"] = Field(
        default="openai",
        description="LLM provider to use (openai, anthropic, azure for both Azure OpenAI and Azure Claude)"
    )
    
    openai_api_key: str | None = Field(default=None, description="OpenAI API key")
    openai_model: str = Field(
        default="gpt-4-turbo-preview",
        description="OpenAI model to use"
    )
    
    anthropic_api_key: str | None = Field(default=None, description="Anthropic API key")
    anthropic_model: str = Field(
        default="claude-3-5-sonnet-20241022",
        description="Anthropic model to use"
    )
    
    azure_openai_api_key: str | None = Field(default=None, description="Azure API key (for both OpenAI and Claude)")
    azure_openai_endpoint: str | None = Field(default=None, description="Azure endpoint (supports both OpenAI and Anthropic formats)")
    azure_openai_deployment: str | None = Field(default=None, description="Azure deployment name")
    azure_openai_api_version: str = Field(
        default="2024-02-15-preview",
        description="Azure API version"
    )

    # Debugger Configuration
    cdb_path: Path = Field(
        default=Path(r"C:\Program Files (x86)\Windows Kits\10\Debuggers\x64\cdb.exe"),
        description="Path to CDB executable"
    )
    windbg_path: Path = Field(
        default=Path(r"C:\Program Files (x86)\Windows Kits\10\Debuggers\x64\windbg.exe"),
        description="Path to WinDbg executable"
    )
    symbol_path: str = Field(
        default=r"SRV*c:\symbols*https://msdl.microsoft.com/download/symbols",
        description="Symbol server path"
    )
    sos_dll_path: Path | None = Field(
        default=None,
        description="Path to SOS.dll for .NET dump analysis (optional - auto-detect if not specified). Use this when analyzing dumps from different .NET runtime versions."
    )
    mscordacwks_path: Path | None = Field(
        default=None,
        description="Path to mscordacwks.dll (or mscordaccore.dll) for .NET dump analysis (optional - auto-download if not specified). MUST match exact runtime build version. Critical for dump analysis."
    )

    # Application Configuration
    log_level: str = Field(default="INFO", description="Logging level")
    max_iterations: int = Field(
        default=15,
        description="Maximum number of debugger iterations"
    )
    command_timeout: int = Field(
        default=600,
        description="Timeout for debugger commands in seconds (10 minutes for slow commands like !dumpheap, ~*e !CLRStack)"
    )
    enable_data_model_commands: bool = Field(
        default=True,
        description="Whether to allow data model (dx) commands"
    )
    max_command_retries: int = Field(
        default=3,
        description="Maximum number of retries for failed commands with syntax errors"
    )
    max_hypothesis_attempts: int = Field(
        default=8,
        description="Maximum number of hypothesis attempts before forcing investigation"
    )
    
    # Interactive chat mode
    max_chat_messages: int = Field(
        default=50,
        description="Maximum number of messages in chat history"
    )
    chat_session_timeout_minutes: int = Field(
        default=30,
        description="Maximum time for interactive chat session in minutes"
    )
    graph_recursion_limit: int = Field(
        default=200,
        description="LangGraph recursion limit - max graph iterations (each chat question counts as 1)"
    )
    
    # Evidence management
    evidence_storage_threshold: int = Field(
        default=250000,
        description="Size threshold for chunked analysis (250KB - matches chunk size)"
    )
    evidence_chunk_size: int = Field(
        default=250000,
        description="Chunk size for LLM analysis (250KB optimized for Claude Sonnet 4.5)"
    )
    chunk_analysis_delay: float = Field(
        default=2.0,
        description="Delay in seconds between chunk analyses to avoid rate limits (when >5 chunks)"
    )
    use_embeddings: bool = Field(
        default=True,
        description="Whether to use embeddings for semantic search (requires OpenAI or Azure OpenAI API)"
    )
    embeddings_provider: str = Field(
        default="openai",
        description="Embeddings provider: 'openai' or 'azure'"
    )
    embeddings_model: str = Field(
        default="text-embedding-3-small",
        description="Embeddings model name"
    )
    azure_embeddings_deployment: str | None = Field(
        default=None,
        description="Azure OpenAI embeddings deployment name (required if embeddings_provider=azure)"
    )
    azure_embeddings_endpoint: str | None = Field(
        default=None,
        description="Azure OpenAI embeddings endpoint (defaults to azure_openai_endpoint if not set)"
    )
    azure_embeddings_api_key: str | None = Field(
        default=None,
        description="Azure OpenAI embeddings API key (defaults to azure_openai_api_key if not set)"
    )
    
    # Session management
    sessions_base_dir: str = Field(
        default=".sessions",
        description="Base directory for analysis sessions"
    )
    session_cleanup_days: int = Field(
        default=7,
        description="Delete sessions older than this many days"
    )
    session_keep_recent: int = Field(
        default=5,
        description="Always keep this many most recent sessions"
    )

    def get_debugger_path(self, prefer_cdb: bool = True) -> Path:
        """Get the debugger executable path."""
        path = self.cdb_path if prefer_cdb else self.windbg_path
        if not path.exists():
            raise FileNotFoundError(
                f"Debugger not found at {path}. "
                "Please install Windows Debugging Tools or update the path in .env"
            )
        return path


# Global settings instance
settings = Settings()
