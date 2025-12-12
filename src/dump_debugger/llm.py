"""LLM provider utilities for different API providers."""

from typing import Any

from langchain_anthropic import ChatAnthropic
from langchain_core.language_models import BaseChatModel
from langchain_openai import AzureChatOpenAI, ChatOpenAI

from dump_debugger.config import settings


def get_llm(temperature: float = 0.0) -> BaseChatModel:
    """Get the configured LLM instance.
    
    Args:
        temperature: Model temperature (0.0 for deterministic, higher for creative)
        
    Returns:
        Configured LLM instance
        
    Raises:
        ValueError: If provider is not configured or invalid
    """
    provider = settings.llm_provider.lower()
    
    if provider == "openai":
        if not settings.openai_api_key:
            raise ValueError("OpenAI API key not configured. Set OPENAI_API_KEY in .env")
        
        return ChatOpenAI(
            model=settings.openai_model,
            temperature=temperature,
            api_key=settings.openai_api_key,
            request_timeout=60,  # 60 second timeout
        )
    
    elif provider == "anthropic":
        if not settings.anthropic_api_key:
            raise ValueError("Anthropic API key not configured. Set ANTHROPIC_API_KEY in .env")
        
        return ChatAnthropic(
            model=settings.anthropic_model,
            temperature=temperature,
            api_key=settings.anthropic_api_key,
            timeout=60,  # 60 second timeout
        )
    
    elif provider == "azure":
        if not settings.azure_openai_api_key or not settings.azure_openai_endpoint:
            raise ValueError(
                "Azure OpenAI not configured. Set AZURE_OPENAI_API_KEY and "
                "AZURE_OPENAI_ENDPOINT in .env"
            )
        
        return AzureChatOpenAI(
            azure_deployment=settings.azure_openai_deployment,
            api_version=settings.azure_openai_api_version,
            azure_endpoint=settings.azure_openai_endpoint,
            api_key=settings.azure_openai_api_key,
            temperature=temperature,
            request_timeout=60,  # 60 second timeout
        )
    
    else:
        raise ValueError(
            f"Invalid LLM provider: {provider}. "
            "Choose from: openai, anthropic, azure"
        )


def get_structured_llm(temperature: float = 0.0) -> BaseChatModel:
    """Get an LLM instance configured for structured output.
    
    Args:
        temperature: Model temperature
        
    Returns:
        LLM instance with JSON mode enabled (if supported)
    """
    llm = get_llm(temperature)
    
    # For OpenAI and Azure, we can enable JSON mode
    if isinstance(llm, (ChatOpenAI, AzureChatOpenAI)):
        llm.model_kwargs = {"response_format": {"type": "json_object"}}
    
    return llm
