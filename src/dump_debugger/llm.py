"""LLM provider utilities for different API providers."""

from typing import Any

from anthropic import AnthropicFoundry
from langchain_anthropic import ChatAnthropic
from langchain_core.language_models import BaseChatModel
from langchain_core.embeddings import Embeddings
from langchain_openai import AzureChatOpenAI, ChatOpenAI, OpenAIEmbeddings, AzureOpenAIEmbeddings
from langchain_ollama import ChatOllama, OllamaEmbeddings
from rich.console import Console

try:
    from azure.ai.inference import ChatCompletionsClient
    from azure.ai.inference.models import SystemMessage as AzureSystemMessage
    from azure.ai.inference.models import UserMessage as AzureUserMessage
    from azure.core.credentials import AzureKeyCredential
    AZURE_AI_AVAILABLE = True
except ImportError:
    AZURE_AI_AVAILABLE = False

from dump_debugger.config import settings
from dump_debugger.token_tracker import create_callback

console = Console()

# LLM instance cache to avoid creating duplicates
_llm_cache: dict[str, BaseChatModel] = {}


def get_llm(temperature: float = 0.0) -> BaseChatModel:
    """Get the configured LLM instance.
    
    Args:
        temperature: Model temperature (0.0 for deterministic, higher for creative)
        
    Returns:
        Configured LLM instance (cached to avoid duplicates)
        
    Raises:
        ValueError: If provider is not configured or invalid
    """
    provider = settings.llm_provider.lower()
    
    # Check cache first (key includes provider, model, and temperature)
    cache_key = f"{provider}:{temperature}"
    if provider == "ollama":
        cache_key = f"ollama:{settings.local_llm_model}:{temperature}"
    elif provider == "azure":
        cache_key = f"azure:{settings.azure_openai_deployment}:{temperature}"
    elif provider == "openai":
        cache_key = f"openai:{settings.openai_model}:{temperature}"
    elif provider == "anthropic":
        cache_key = f"anthropic:{settings.anthropic_model}:{temperature}"
    
    if cache_key in _llm_cache:
        console.print(f"[dim]♻️ Reusing cached LLM: {provider} (temp={temperature})[/dim]")
        return _llm_cache[cache_key]
    
    # Determine if this is a local provider for token tracking
    is_local = (provider == "ollama")
    
    # Create token counting callback
    try:
        callback = create_callback(is_local=is_local)
        callbacks = [callback]
    except Exception:
        callbacks = []
    
    if provider == "openai":
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
        _llm_cache[cache_key] = llm
        return llm
    
    elif provider == "anthropic":
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
        _llm_cache[cache_key] = llm
        return llm
    
    elif provider == "azure":
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
            _llm_cache[cache_key] = llm
            return llm
    
    elif provider == "ollama":
        if not settings.use_local_llm:
            raise ValueError("Ollama not enabled. Set USE_LOCAL_LLM=true in .env")
        
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
            f"Invalid LLM provider: {provider}. "
            "Choose from: openai, anthropic, azure, ollama"
        )


def get_structured_llm(temperature: float = 0.0) -> BaseChatModel:
    """Get an LLM instance configured for structured output.
    
    Args:
        temperature: Model temperature
        
    Returns:
        LLM instance with JSON mode enabled (if supported)
    """
    llm = get_llm(temperature)
    
    # For OpenAI and Azure OpenAI, we can enable JSON mode
    if isinstance(llm, (ChatOpenAI, AzureChatOpenAI)):
        llm.model_kwargs = {"response_format": {"type": "json_object"}}
    # For Claude/Anthropic, JSON mode is not supported via a parameter
    # Instead, the prompts must explicitly request JSON in <JSON></JSON> tags or similar
    # and we rely on the prompt engineering
    
    return llm


def get_embeddings() -> Embeddings:
    """Get embeddings model based on configured LLM provider.
    
    Returns:
        Embeddings instance for semantic search
        
    Raises:
        ValueError: If provider doesn't support embeddings or is not configured
    """
    provider = settings.llm_provider.lower()
    
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
            "Deploy 'text-embedding-3-small' in Azure OpenAI and set AZURE_OPENAI_EMBEDDINGS_DEPLOYMENT env var. "
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

