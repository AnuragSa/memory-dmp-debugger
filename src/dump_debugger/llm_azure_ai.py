"""Azure AI Foundry LLM wrapper for LangChain compatibility."""

from typing import Any, Iterator, List, Optional

from azure.ai.inference import ChatCompletionsClient
from azure.ai.inference.models import (
    AssistantMessage,
    ChatCompletions,
    ChatRequestMessage,
    SystemMessage,
    UserMessage,
)
from azure.core.credentials import AzureKeyCredential
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.messages import SystemMessage as LangChainSystemMessage
from langchain_core.outputs import ChatGeneration, ChatResult


class AzureAIChatWrapper(BaseChatModel):
    """Wrapper for Azure AI Foundry Chat API to work with LangChain.
    
    This enables using models from Azure AI Foundry (including Claude, GPT-4, etc.)
    with LangChain-based applications.
    """
    
    endpoint: str
    api_key: str
    model: str
    temperature: float = 0.0
    max_tokens: int = 4096
    top_p: float = 1.0
    client: Optional[ChatCompletionsClient] = None
    
    class Config:
        """Pydantic configuration."""
        arbitrary_types_allowed = True
    
    def __init__(self, **kwargs: Any) -> None:
        """Initialize the Azure AI chat wrapper."""
        super().__init__(**kwargs)
        self.client = ChatCompletionsClient(
            endpoint=self.endpoint,
            credential=AzureKeyCredential(self.api_key)
        )
    
    @property
    def _llm_type(self) -> str:
        """Return type of LLM."""
        return "azure_ai_foundry"
    
    def _convert_message_to_azure(self, message: BaseMessage) -> ChatRequestMessage:
        """Convert LangChain message to Azure AI message format."""
        if isinstance(message, HumanMessage):
            return UserMessage(content=message.content)
        elif isinstance(message, AIMessage):
            return AssistantMessage(content=message.content)
        elif isinstance(message, LangChainSystemMessage):
            return SystemMessage(content=message.content)
        else:
            # Default to user message for unknown types
            return UserMessage(content=str(message.content))
    
    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        """Generate chat completions for the given messages."""
        # Convert LangChain messages to Azure AI format
        azure_messages = [self._convert_message_to_azure(msg) for msg in messages]
        
        # Prepare request parameters
        request_params: dict[str, Any] = {
            "messages": azure_messages,
            "model": self.model,
            "temperature": kwargs.get("temperature", self.temperature),
            "max_tokens": kwargs.get("max_tokens", self.max_tokens),
            "top_p": kwargs.get("top_p", self.top_p),
        }
        
        if stop:
            request_params["stop"] = stop
        
        # Make the API call
        if self.client is None:
            raise ValueError("Client not initialized")
            
        response: ChatCompletions = self.client.complete(**request_params)
        
        # Convert response to LangChain format
        if not response.choices:
            raise ValueError("No choices returned from Azure AI API")
        
        choice = response.choices[0]
        message_content = choice.message.content or ""
        
        # Create AIMessage from response
        ai_message = AIMessage(content=message_content)
        
        # Create generation with metadata
        generation = ChatGeneration(
            message=ai_message,
            generation_info={
                "finish_reason": choice.finish_reason,
                "model": response.model,
                "usage": {
                    "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
                    "completion_tokens": response.usage.completion_tokens if response.usage else 0,
                    "total_tokens": response.usage.total_tokens if response.usage else 0,
                },
            },
        )
        
        return ChatResult(generations=[generation])
    
    def _stream(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> Iterator[ChatGeneration]:
        """Stream chat completions (not implemented)."""
        raise NotImplementedError("Streaming not yet implemented for Azure AI wrapper")
    
    @property
    def _identifying_params(self) -> dict[str, Any]:
        """Return identifying parameters."""
        return {
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "endpoint": self.endpoint,
        }
