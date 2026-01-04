"""Token usage tracking for LLM calls."""

from typing import Any, Dict
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult
from rich.console import Console

console = Console()


def estimate_tokens(text: str) -> int:
    """Rough estimation: ~4 characters per token for English text."""
    return len(text) // 4


class TokenUsageTracker:
    """Global token usage tracker for all LLM calls."""
    
    def __init__(self):
        self.local_input_tokens = 0
        self.local_output_tokens = 0
        self.cloud_input_tokens = 0
        self.cloud_output_tokens = 0
        self.local_calls = 0
        self.cloud_calls = 0
        
    def add_local_usage(self, prompt_tokens: int, completion_tokens: int):
        """Add local LLM usage."""
        self.local_input_tokens += prompt_tokens
        self.local_output_tokens += completion_tokens
        self.local_calls += 1
        
    def add_cloud_usage(self, prompt_tokens: int, completion_tokens: int):
        """Add cloud LLM usage."""
        self.cloud_input_tokens += prompt_tokens
        self.cloud_output_tokens += completion_tokens
        self.cloud_calls += 1
    
    def get_summary(self) -> Dict[str, Any]:
        """Get usage summary."""
        return {
            'local': {
                'input_tokens': self.local_input_tokens,
                'output_tokens': self.local_output_tokens,
                'total_tokens': self.local_input_tokens + self.local_output_tokens,
                'calls': self.local_calls
            },
            'cloud': {
                'input_tokens': self.cloud_input_tokens,
                'output_tokens': self.cloud_output_tokens,
                'total_tokens': self.cloud_input_tokens + self.cloud_output_tokens,
                'calls': self.cloud_calls
            },
            'total_input_tokens': self.local_input_tokens + self.cloud_input_tokens,
            'total_output_tokens': self.local_output_tokens + self.cloud_output_tokens,
            'total_tokens': self.local_input_tokens + self.local_output_tokens + self.cloud_input_tokens + self.cloud_output_tokens,
            'total_calls': self.local_calls + self.cloud_calls
        }
    
    def print_summary(self):
        """Print formatted usage summary."""
        console.print("\n[bold cyan]═══════════════════════════════════════════════════[/bold cyan]")
        console.print("[bold cyan]TOKEN USAGE SUMMARY[/bold cyan]")
        console.print("[bold cyan]═══════════════════════════════════════════════════[/bold cyan]\n")
        
        if self.local_calls > 0:
            local_total = self.local_input_tokens + self.local_output_tokens
            console.print(f"[green]Local LLM (Ollama):[/green]")
            console.print(f"  Calls: {self.local_calls:,}")
            console.print(f"  Input tokens: {self.local_input_tokens:,}")
            console.print(f"  Output tokens: {self.local_output_tokens:,}")
            console.print(f"  Total: {local_total:,}\n")
        
        if self.cloud_calls > 0:
            cloud_total = self.cloud_input_tokens + self.cloud_output_tokens
            console.print(f"[blue]Cloud LLM (Anthropic/OpenAI/Azure):[/blue]")
            console.print(f"  Calls: {self.cloud_calls:,}")
            console.print(f"  Input tokens: {self.cloud_input_tokens:,}")
            console.print(f"  Output tokens: {self.cloud_output_tokens:,}")
            console.print(f"  Total: {cloud_total:,}\n")
        
        total_input = self.local_input_tokens + self.cloud_input_tokens
        total_output = self.local_output_tokens + self.cloud_output_tokens
        total = total_input + total_output
        
        console.print(f"[bold]Grand Total:[/bold]")
        console.print(f"  Input tokens: {total_input:,}")
        console.print(f"  Output tokens: {total_output:,}")
        console.print(f"  Total tokens: {total:,}")
        console.print(f"  Total calls: {self.local_calls + self.cloud_calls:,}\n")
    
    def reset(self):
        """Reset all counters."""
        self.local_input_tokens = 0
        self.local_output_tokens = 0
        self.cloud_input_tokens = 0
        self.cloud_output_tokens = 0
        self.local_calls = 0
        self.cloud_calls = 0


# Global tracker instance
_tracker = TokenUsageTracker()


def get_tracker() -> TokenUsageTracker:
    """Get the global token tracker."""
    return _tracker


class TokenCountingCallback(BaseCallbackHandler):
    """Callback handler to track token usage."""
    
    def __init__(self, is_local: bool = False):
        super().__init__()
        self.is_local = is_local
    
    def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:
        """Track tokens when LLM call completes."""
        try:
            if not response.llm_output:
                # Try to estimate from response text for local LLMs
                if self.is_local:
                    try:
                        total_output_tokens = 0
                        for generation_list in response.generations:
                            for gen in generation_list:
                                if hasattr(gen, 'text') and gen.text:
                                    est_output = estimate_tokens(gen.text)
                                    total_output_tokens += est_output
                        
                        if total_output_tokens > 0:
                            _tracker.add_local_usage(0, total_output_tokens)
                    except Exception:
                        pass
                return
            
            # Try different provider formats
            usage = None
            if 'token_usage' in response.llm_output:
                usage = response.llm_output['token_usage']
            elif 'usage' in response.llm_output:
                usage = response.llm_output['usage']
            else:
                return
            
            if not isinstance(usage, dict):
                return
            
            # Try different key names for token counts
            prompt_tokens = (
                usage.get('input_tokens') or 
                usage.get('prompt_tokens') or 
                0
            )
            completion_tokens = (
                usage.get('output_tokens') or 
                usage.get('completion_tokens') or 
                0
            )
            
            if prompt_tokens or completion_tokens:
                if self.is_local:
                    _tracker.add_local_usage(prompt_tokens, completion_tokens)
                else:
                    _tracker.add_cloud_usage(prompt_tokens, completion_tokens)
                
        except Exception:
            # Don't crash the analysis if token tracking fails
            pass


def create_callback(is_local: bool = False) -> TokenCountingCallback:
    """Create a token counting callback."""
    return TokenCountingCallback(is_local=is_local)
