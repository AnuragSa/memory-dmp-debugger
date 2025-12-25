"""Tiered LLM routing strategy for cost and performance optimization."""

from enum import Enum
from typing import Any, Dict

from langchain_core.language_models import BaseChatModel
from rich.console import Console

from dump_debugger.config import settings
from dump_debugger.llm import get_llm

console = Console()


class LLMTier(Enum):
    """LLM tier for routing decisions."""
    LOCAL = "local"  # Fast, free, simple tasks (Ollama)
    CLOUD = "cloud"  # Powerful, expensive, complex tasks (Claude/GPT-4)


class TaskComplexity(Enum):
    """Task complexity levels for routing."""
    SIMPLE = "simple"      # Structured data parsing, pattern matching
    MODERATE = "moderate"  # Some reasoning, data interpretation
    COMPLEX = "complex"    # Deep analysis, multi-step reasoning


class LLMRouter:
    """Routes LLM requests to appropriate tier based on task complexity."""
    
    def __init__(self):
        """Initialize the LLM router."""
        self.use_tiered = settings.use_tiered_llm and settings.use_local_llm
        self._local_llm: BaseChatModel | None = None
        self._cloud_llm: BaseChatModel | None = None
    
    @property
    def local_llm(self) -> BaseChatModel:
        """Get or create local LLM instance."""
        if self._local_llm is None:
            # Temporarily override provider to get Ollama instance
            original_provider = settings.llm_provider
            settings.llm_provider = "ollama"
            self._local_llm = get_llm(temperature=0.0)
            settings.llm_provider = original_provider
            console.print(f"[dim]🤖 Initialized local LLM: {settings.local_llm_model}[/dim]")
        return self._local_llm
    
    @property
    def cloud_llm(self) -> BaseChatModel:
        """Get or create cloud LLM instance."""
        if self._cloud_llm is None:
            # Use configured cloud provider
            original_provider = settings.llm_provider
            settings.llm_provider = settings.cloud_llm_provider
            self._cloud_llm = get_llm(temperature=0.0)
            settings.llm_provider = original_provider
            console.print(f"[dim]☁️ Initialized cloud LLM: {settings.cloud_llm_provider}[/dim]")
        return self._cloud_llm
    
    def get_llm_for_task(
        self, 
        complexity: TaskComplexity,
        force_tier: LLMTier | None = None
    ) -> BaseChatModel:
        """Get appropriate LLM for task complexity.
        
        Args:
            complexity: Task complexity level
            force_tier: Force specific tier (overrides routing logic)
            
        Returns:
            Appropriate LLM instance
        """
        # If tiered routing is disabled, always use configured LLM
        if not self.use_tiered:
            llm = get_llm(temperature=0.0)
            console.print(f"[dim]🤖 LLM: {settings.llm_provider} (tiered routing disabled)[/dim]")
            return llm
        
        # If specific tier is requested, use it
        if force_tier == LLMTier.LOCAL:
            console.print(f"[dim]🤖 LLM: local ({settings.local_llm_model}) [forced][/dim]")
            return self.local_llm
        elif force_tier == LLMTier.CLOUD:
            console.print(f"[dim]☁️ LLM: cloud ({settings.cloud_llm_provider}) [forced][/dim]")
            return self.cloud_llm
        
        # Route based on complexity
        if complexity == TaskComplexity.SIMPLE:
            # Use local LLM for simple tasks (parsing, extraction)
            console.print(f"[dim]🤖 LLM: local ({settings.local_llm_model}) [simple task][/dim]")
            return self.local_llm
        elif complexity == TaskComplexity.MODERATE:
            # Use local LLM for moderate tasks if available, otherwise cloud
            try:
                console.print(f"[dim]🤖 LLM: local ({settings.local_llm_model}) [moderate task][/dim]")
                return self.local_llm
            except Exception:
                console.print(f"[dim]☁️ LLM: cloud ({settings.cloud_llm_provider}) [moderate task, local failed][/dim]")
                return self.cloud_llm
        else:  # COMPLEX
            # Always use cloud LLM for complex reasoning
            console.print(f"[dim]☁️ LLM: cloud ({settings.cloud_llm_provider}) [complex task][/dim]")
            return self.cloud_llm
    
    def get_llm_for_command(self, command: str) -> tuple[BaseChatModel, TaskComplexity]:
        """Get appropriate LLM based on debugger command type.
        
        Args:
            command: Debugger command string
            
        Returns:
            Tuple of (LLM instance, complexity level)
        """
        # Determine complexity based on command
        complexity = self._classify_command_complexity(command)
        llm = self.get_llm_for_task(complexity)
        return llm, complexity
    
    def _classify_command_complexity(self, command: str) -> TaskComplexity:
        """Classify command complexity for routing.
        
        Args:
            command: Debugger command string
            
        Returns:
            Task complexity level
        """
        command_lower = command.lower().strip()
        
        # SIMPLE: Structured output, minimal interpretation needed
        simple_patterns = [
            "~*k",          # Thread stacks (just stack frames)
            "!threads",     # Thread list (tabular data)
            "!syncblk",     # Sync blocks (tabular data)
        ]
        
        # MODERATE: Some interpretation, medium-sized data
        moderate_patterns = [
            "!dumpheap -stat",  # Heap stats (tables + some analysis)
            "!gcheap -stat",    # GC heap stats
            "!finalizequeue",   # Finalizer queue
        ]
        
        # COMPLEX: Deep analysis required, large data, multi-step reasoning
        complex_patterns = [
            "!clrstack",        # Stack analysis (exception context, local vars)
            "~*e !clrstack",    # All thread stacks (comprehensive)
            "!dumpheap -type",  # Heap objects (need object analysis)
            "!gcroot",          # Root analysis (complex graphs)
            "!dso",            # Stack objects (context-heavy)
        ]
        
        # Check patterns
        for pattern in simple_patterns:
            if pattern in command_lower:
                return TaskComplexity.SIMPLE
        
        for pattern in moderate_patterns:
            if pattern in command_lower:
                return TaskComplexity.MODERATE
        
        for pattern in complex_patterns:
            if pattern in command_lower:
                return TaskComplexity.COMPLEX
        
        # Default to moderate for unknown commands
        return TaskComplexity.MODERATE
    
    def estimate_cost_savings(self, command: str, output_size: int) -> Dict[str, Any]:
        """Estimate cost savings from tiered routing.
        
        Args:
            command: Debugger command
            output_size: Size of command output in bytes
            
        Returns:
            Dictionary with cost estimates
        """
        if not self.use_tiered:
            return {"savings": 0, "tier": "cloud-only"}
        
        complexity = self._classify_command_complexity(command)
        
        # Rough token estimates (1 token ≈ 4 bytes)
        tokens = output_size // 4
        
        # Cost estimates (per 1M tokens)
        # Claude 4.5: ~$3/M input, ~$15/M output
        # Llama 3.1 14B: Free (local)
        cloud_cost = (tokens / 1_000_000) * 3.0  # Input cost estimate
        local_cost = 0.0
        
        if complexity == TaskComplexity.SIMPLE:
            savings = cloud_cost
            tier = "local"
        elif complexity == TaskComplexity.MODERATE:
            savings = cloud_cost * 0.7  # Assume 70% on local
            tier = "local-hybrid"
        else:
            savings = 0
            tier = "cloud"
        
        return {
            "tier": tier,
            "complexity": complexity.value,
            "estimated_tokens": tokens,
            "cloud_cost_usd": round(cloud_cost, 4),
            "local_cost_usd": local_cost,
            "savings_usd": round(savings, 4),
        }


# Global router instance
llm_router = LLMRouter()
