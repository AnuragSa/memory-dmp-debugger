"""LLM provider utilities for different API providers."""

import time
from pathlib import Path
from typing import Any

from anthropic import AnthropicFoundry
from langchain_anthropic import ChatAnthropic
from langchain_core.language_models import BaseChatModel
from langchain_core.embeddings import Embeddings
from langchain_core.messages import BaseMessage
from langchain_openai import AzureChatOpenAI, ChatOpenAI, OpenAIEmbeddings, AzureOpenAIEmbeddings
from langchain_ollama import ChatOllama, OllamaEmbeddings
from pydantic import PrivateAttr
from rich.console import Console
from rich.panel import Panel
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
)
import logging

try:
    from azure.ai.inference import ChatCompletionsClient
    from azure.ai.inference.models import SystemMessage as AzureSystemMessage
    from azure.ai.inference.models import UserMessage as AzureUserMessage
    from azure.core.credentials import AzureKeyCredential
    AZURE_AI_AVAILABLE = True
except ImportError:
    AZURE_AI_AVAILABLE = False

from dump_debugger.config import settings
from dump_debugger.security.redactor import DataRedactor, load_custom_patterns
from dump_debugger.token_tracker import create_callback

console = Console()

# LLM instance cache to avoid creating duplicates
_llm_cache: dict[str, BaseChatModel] = {}

# Global redactor instance (initialized on first use)
_redactor: DataRedactor | None = None


def get_llm(temperature: float = 0.0, session_id: str | None = None) -> BaseChatModel:
    """Get the configured LLM instance.
    
    Args:
        temperature: Model temperature (0.0 for deterministic, higher for creative)
        session_id: Session ID for audit logging (optional)
        
    Returns:
        Configured LLM instance (cached to avoid duplicates)
        
    Raises:
        ValueError: If provider is not configured or invalid
    """
    # Determine effective provider
    # Priority: local_only_mode forces ollama, otherwise use llm_provider
    effective_provider = settings.llm_provider.lower()
    
    # SECURITY: Enforce local-only mode - forces Ollama for reasoning
    if settings.local_only_mode:
        effective_provider = "ollama"
    
    # Check cache first (key includes provider, model, and temperature)
    cache_key = f"{effective_provider}:{temperature}"
    if effective_provider == "ollama":
        cache_key = f"ollama:{settings.local_llm_model}:{temperature}"
    elif effective_provider == "azure":
        cache_key = f"azure:{settings.azure_openai_deployment}:{temperature}"
    elif effective_provider == "openai":
        cache_key = f"openai:{settings.openai_model}:{temperature}"
    elif effective_provider == "anthropic":
        cache_key = f"anthropic:{settings.anthropic_model}:{temperature}"
    
    if cache_key in _llm_cache:
        console.print(f"[dim]♻️ Reusing cached LLM: {effective_provider} (temp={temperature})[/dim]")
        return _llm_cache[cache_key]
    
    # Determine if this is a local provider for token tracking
    is_local = (effective_provider == "ollama")
    
    # Create token counting callback
    try:
        callback = create_callback(is_local=is_local)
        callbacks = [callback]
    except Exception:
        callbacks = []
    
    if effective_provider == "openai":
        if not settings.openai_api_key:
            raise ValueError("OpenAI API key not configured. Set OPENAI_API_KEY in .env")
        
        llm = ChatOpenAI(
            model=settings.openai_model,
            temperature=temperature,
            api_key=settings.openai_api_key,
            max_tokens=32768,
            request_timeout=60,
            callbacks=callbacks,
        )
        # Wrap with redaction for cloud provider
        llm = _wrap_with_redaction(llm, "openai", session_id)
        _llm_cache[cache_key] = llm
        return llm
    
    elif effective_provider == "anthropic":
        if not settings.anthropic_api_key:
            raise ValueError("Anthropic API key not configured. Set ANTHROPIC_API_KEY in .env")
        
        llm = ChatAnthropic(
            model=settings.anthropic_model,
            temperature=temperature,
            api_key=settings.anthropic_api_key,
            max_tokens=32768,
            timeout=60,
            callbacks=callbacks,
        )
        # Wrap with redaction for cloud provider
        llm = _wrap_with_redaction(llm, "anthropic", session_id)
        _llm_cache[cache_key] = llm
        return llm
    
    elif effective_provider == "azure":
        if not settings.azure_openai_api_key or not settings.azure_openai_endpoint:
            raise ValueError(
                "Azure not configured. Set AZURE_OPENAI_API_KEY and "
                "AZURE_OPENAI_ENDPOINT in .env"
            )
        
        # Auto-detect if this is Azure AI Foundry or Azure OpenAI
        endpoint = settings.azure_openai_endpoint
        
        if "services.ai.azure.com" in endpoint.lower():
            # Azure AI Foundry
            llm = ChatAnthropic(
                model=settings.azure_openai_deployment or "claude-3-5-sonnet",
                temperature=temperature,
                anthropic_api_key=settings.azure_openai_api_key,
                base_url=endpoint,
                max_tokens=32768,
                timeout=60,
                callbacks=callbacks,
            )
            # Wrap with redaction for cloud provider
            llm = _wrap_with_redaction(llm, "azure-foundry", session_id)
            _llm_cache[cache_key] = llm
            return llm
        else:
            # Azure OpenAI
            llm = AzureChatOpenAI(
                azure_deployment=settings.azure_openai_deployment,
                api_version=settings.azure_openai_api_version,
                azure_endpoint=settings.azure_openai_endpoint,
                api_key=settings.azure_openai_api_key,
                temperature=temperature,
                max_tokens=32768,
                request_timeout=60,
                callbacks=callbacks,
            )
            # Wrap with redaction for cloud provider
            llm = _wrap_with_redaction(llm, "azure-openai", session_id)
            _llm_cache[cache_key] = llm
            return llm
    
    elif effective_provider == "ollama":
        llm = ChatOllama(
            model=settings.local_llm_model,
            base_url=settings.local_llm_base_url,
            temperature=temperature,
            timeout=settings.local_llm_timeout,
            num_ctx=settings.local_llm_context_size,
            callbacks=callbacks,
        )
        _llm_cache[cache_key] = llm
        return llm
    
    else:
        raise ValueError(
            f"Invalid LLM provider: {effective_provider}. "
            "Choose from: openai, anthropic, azure, ollama"
        )


def get_llm_for_provider(
    provider: str,
    temperature: float = 0.0,
    session_id: str | None = None
) -> BaseChatModel:
    """Get LLM instance for a specific provider without modifying global settings.
    
    This is used by the LLM router to get cloud/local LLM instances without
    mutating settings.llm_provider, which could affect embeddings selection.
    
    Args:
        provider: The provider to use ('openai', 'anthropic', 'azure', 'ollama')
        temperature: Model temperature
        session_id: Session ID for audit logging
        
    Returns:
        LLM instance for the specified provider
    """
    provider = provider.lower()
    
    # Build cache key
    cache_key = f"explicit:{provider}:{temperature}"
    if provider == "ollama":
        cache_key = f"explicit:ollama:{settings.local_llm_model}:{temperature}"
    elif provider == "azure":
        cache_key = f"explicit:azure:{settings.azure_openai_deployment}:{temperature}"
    elif provider == "openai":
        cache_key = f"explicit:openai:{settings.openai_model}:{temperature}"
    elif provider == "anthropic":
        cache_key = f"explicit:anthropic:{settings.anthropic_model}:{temperature}"
    
    if cache_key in _llm_cache:
        return _llm_cache[cache_key]
    
    is_local = (provider == "ollama")
    
    try:
        callback = create_callback(is_local=is_local)
        callbacks = [callback]
    except Exception:
        callbacks = []
    
    if provider == "openai":
        if not settings.openai_api_key:
            raise ValueError("OpenAI API key not configured")
        llm = ChatOpenAI(
            model=settings.openai_model,
            temperature=temperature,
            api_key=settings.openai_api_key,
            max_tokens=32768,
            request_timeout=60,
            callbacks=callbacks,
        )
        llm = _wrap_with_redaction(llm, "openai", session_id)
        
    elif provider == "anthropic":
        if not settings.anthropic_api_key:
            raise ValueError("Anthropic API key not configured")
        llm = ChatAnthropic(
            model=settings.anthropic_model,
            temperature=temperature,
            api_key=settings.anthropic_api_key,
            max_tokens=32768,
            timeout=60,
            callbacks=callbacks,
        )
        llm = _wrap_with_redaction(llm, "anthropic", session_id)
        
    elif provider == "azure":
        if not settings.azure_openai_api_key or not settings.azure_openai_endpoint:
            raise ValueError("Azure not configured")
        endpoint = settings.azure_openai_endpoint
        if "services.ai.azure.com" in endpoint.lower():
            llm = ChatAnthropic(
                model=settings.azure_openai_deployment or "claude-3-5-sonnet",
                temperature=temperature,
                anthropic_api_key=settings.azure_openai_api_key,
                base_url=endpoint,
                max_tokens=32768,
                timeout=60,
                callbacks=callbacks,
            )
            llm = _wrap_with_redaction(llm, "azure-foundry", session_id)
        else:
            llm = AzureChatOpenAI(
                azure_deployment=settings.azure_openai_deployment,
                api_version=settings.azure_openai_api_version,
                azure_endpoint=settings.azure_openai_endpoint,
                api_key=settings.azure_openai_api_key,
                temperature=temperature,
                max_tokens=32768,
                request_timeout=60,
                callbacks=callbacks,
            )
            llm = _wrap_with_redaction(llm, "azure-openai", session_id)
            
    elif provider == "ollama":
        llm = ChatOllama(
            model=settings.local_llm_model,
            base_url=settings.local_llm_base_url,
            temperature=temperature,
            timeout=settings.local_llm_timeout,
            num_ctx=settings.local_llm_context_size,
            callbacks=callbacks,
        )
    else:
        raise ValueError(f"Invalid provider: {provider}")
    
    _llm_cache[cache_key] = llm
    return llm


def get_structured_llm(temperature: float = 0.0) -> BaseChatModel:
    """Get an LLM instance configured for structured output.
    
    Args:
        temperature: Model temperature
        
    Returns:
        LLM instance with JSON mode enabled (if supported)
    """
    llm = get_llm(temperature)
    
    # Unwrap if it's a RedactionLLMWrapper to check the underlying LLM type
    underlying_llm = llm.llm if isinstance(llm, RedactionLLMWrapper) else llm
    
    # For OpenAI and Azure OpenAI, we can enable JSON mode
    if isinstance(underlying_llm, (ChatOpenAI, AzureChatOpenAI)):
        underlying_llm.model_kwargs = {"response_format": {"type": "json_object"}}
    # For Claude/Anthropic, JSON mode is not supported via a parameter
    # Instead, the prompts must explicitly request JSON in <JSON></JSON> tags or similar
    # and we rely on the prompt engineering
    
    return llm


def get_embeddings() -> Embeddings:
    """Get embeddings model based on configured embeddings provider.
    
    In LOCAL_ONLY_MODE, embeddings are disabled (raises ValueError) to prevent
    any data from leaving the machine. Callers should fall back to keyword search.
    
    Returns:
        Embeddings instance for semantic search
        
    Raises:
        ValueError: If local-only mode is enabled, provider doesn't support embeddings,
                   or provider is not configured
    """
    # SECURITY: Disable embeddings in local-only mode to prevent cloud calls
    if settings.local_only_mode:
        raise ValueError(
            "🔒 LOCAL-ONLY MODE: Embeddings disabled to prevent cloud calls. "
            "Using keyword search instead."
        )
    
    # Use embeddings_provider setting, fall back to llm_provider for backward compat
    provider = settings.embeddings_provider.lower() if settings.embeddings_provider else settings.llm_provider.lower()
    
    if provider == "openai":
        return OpenAIEmbeddings(
            model="text-embedding-3-small",
            api_key=settings.openai_api_key
        )
    
    elif provider == "azure":
        # For Azure, embeddings require a separate deployment
        # Skip if not configured - will fall back to keyword matching
        raise ValueError(
            "Azure embeddings not configured. "
            "Deploy 'text-embedding-3-small' in Azure OpenAI and set AZURE_EMBEDDINGS_DEPLOYMENT env var. "
            "Falling back to keyword matching."
        )
    
    elif provider == "ollama":
        # Ollama with local embeddings model
        return OllamaEmbeddings(
            model=settings.local_embeddings_model or "nomic-embed-text",
            base_url=settings.local_llm_base_url
        )
    
    elif provider == "anthropic":
        # Anthropic doesn't provide embeddings, fall back to OpenAI
        console.print("[yellow]⚠ Anthropic doesn't provide embeddings, using OpenAI text-embedding-3-small[/yellow]")
        if not settings.openai_api_key:
            raise ValueError("OpenAI API key required for embeddings when using Anthropic LLM")
        return OpenAIEmbeddings(
            model="text-embedding-3-small",
            api_key=settings.openai_api_key
        )
    
    else:
        raise ValueError(f"Embeddings not supported for provider: {provider}")


class RedactionLLMWrapper(BaseChatModel):
    """Wrapper that applies data redaction before sending to cloud LLMs.
    
    This wrapper intercepts all LLM calls, redacts sensitive data, displays
    warnings about cloud usage, and optionally logs redactions for audit.
    """
    
    # Pydantic fields (public)
    llm: BaseChatModel
    provider_name: str
    session_id: str | None = None
    
    # Private state variables (not part of Pydantic model)
    _shown_warning: bool = PrivateAttr(default=False)
    _total_redactions: int = PrivateAttr(default=0)
    
    class Config:
        """Pydantic configuration."""
        arbitrary_types_allowed = True
    
    def model_post_init(self, __context: Any) -> None:
        """Initialize private attributes after model creation."""
        super().model_post_init(__context)
        self._shown_warning = False
        self._total_redactions = 0
    
    def _get_redactor(self) -> DataRedactor:
        """Get or create the global redactor instance."""
        global _redactor
        
        # Always recreate if show_values changed (for debugging session)
        # or if redactor doesn't exist yet
        should_recreate = (
            _redactor is None or 
            (hasattr(_redactor, 'show_values') and _redactor.show_values != settings.show_redacted_values)
        )
        
        if should_recreate:
            # Load custom patterns
            custom_patterns_path = settings.redaction_patterns_path
            custom_patterns = load_custom_patterns(custom_patterns_path)
            
            # Setup audit logging if enabled AND we have a session_id
            audit_log_path = None
            enable_audit = False
            # Use session_id from wrapper or fall back to settings.current_session_id
            session_id_to_use = self.session_id or settings.current_session_id
            if settings.enable_redaction_audit and session_id_to_use:
                audit_log_path = Path(settings.sessions_base_dir) / session_id_to_use / "redaction_audit.log"
                enable_audit = True
            
            _redactor = DataRedactor(
                custom_patterns=custom_patterns,
                enable_audit=enable_audit,
                audit_log_path=audit_log_path,
                redaction_placeholder="[REDACTED]",
                show_values=settings.show_redacted_values
            )
        return _redactor
    
    def _redact_messages(self, messages: list[BaseMessage] | str) -> tuple[list[BaseMessage] | str, int]:
        """Redact sensitive data from messages.
        
        Args:
            messages: List of messages to redact or a string
            
        Returns:
            Tuple of (redacted messages/string, redaction count)
        """
        redactor = self._get_redactor()
        
        # Handle string input (some LangChain code calls invoke with strings)
        if isinstance(messages, str):
            redacted_text, redaction_count = redactor.redact_text(
                messages,
                context=f"{self.provider_name}_call"
            )
            self._total_redactions += redaction_count
            return redacted_text, redaction_count
        
        # Handle list of messages
        redacted_messages = []
        total_redactions = 0
        
        for msg in messages:
            content = msg.content
            if isinstance(content, str):
                redacted_content, redaction_count = redactor.redact_text(
                    content,
                    context=f"{self.provider_name}_call"
                )
                total_redactions += redaction_count
                
                # Create new message with redacted content
                redacted_msg = msg.__class__(content=redacted_content)
                # Copy other attributes
                if hasattr(msg, 'additional_kwargs'):
                    redacted_msg.additional_kwargs = msg.additional_kwargs
                redacted_messages.append(redacted_msg)
            else:
                redacted_messages.append(msg)
        
        self._total_redactions += total_redactions
        return redacted_messages, total_redactions
    
    def _show_cloud_warning(self, redaction_count: int):
        """Display prominent warning about cloud usage."""
        # Warning banner removed - no longer needed
        pass
    
    @retry(
        retry=retry_if_exception_type((Exception,)),
        wait=wait_exponential(multiplier=1, min=1, max=30),
        stop=stop_after_attempt(5),
        before_sleep=lambda retry_state: console.print(
            f"[yellow]⚠️  API error (attempt {retry_state.attempt_number}/5): {retry_state.outcome.exception()}. Retrying in {retry_state.next_action.sleep} seconds...[/yellow]"
        ),
        reraise=True,
    )
    def invoke(self, messages: list[BaseMessage] | str, **kwargs: Any) -> Any:
        """Invoke the LLM with redacted messages.
        
        Args:
            messages: Messages to send (list of BaseMessage or string)
            **kwargs: Additional arguments for LLM
            
        Returns:
            LLM response
        """
        # Redact messages
        redacted_messages, redaction_count = self._redact_messages(messages)
        
        # Show warning
        self._show_cloud_warning(redaction_count)
        
        # Call underlying LLM
        return self.llm.invoke(redacted_messages, **kwargs)
    
    def _generate(self, messages: list[BaseMessage] | str, **kwargs: Any) -> Any:
        """Generate method for LangChain compatibility."""
        redacted_messages, redaction_count = self._redact_messages(messages)
        self._show_cloud_warning(redaction_count)
        return self.llm._generate(redacted_messages, **kwargs)
    
    def __getattr__(self, name: str) -> Any:
        """Delegate attribute access to underlying LLM.
        
        Private attributes are handled by Pydantic's __pydantic_private__ dict.
        Only delegate to underlying LLM if the attribute is not in private storage.
        """
        # Check if this is a private attribute managed by Pydantic
        if name.startswith('_'):
            # Try to get from Pydantic's private storage first
            private_attrs = object.__getattribute__(self, '__pydantic_private__')
            if name in private_attrs:
                return private_attrs[name]
            # If not in private storage, raise AttributeError
            raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")
        
        # Delegate public attributes to underlying LLM
        return getattr(self.llm, name)
    
    @property
    def _llm_type(self) -> str:
        """Return LLM type."""
        return f"redacted_{self.llm._llm_type}"


def _wrap_with_redaction(llm: BaseChatModel, provider_name: str, session_id: str | None) -> BaseChatModel:
    """Wrap an LLM with redaction if not in local-only mode.
    
    Args:
        llm: LLM to wrap
        provider_name: Provider name for logging
        session_id: Session ID for audit logging
        
    Returns:
        Wrapped or original LLM
    """
    if settings.local_only_mode:
        # No need to wrap in local-only mode (already enforced)
        return llm
    
    # Wrap cloud providers with redaction (use keyword arguments for Pydantic)
    return RedactionLLMWrapper(llm=llm, provider_name=provider_name, session_id=session_id)


