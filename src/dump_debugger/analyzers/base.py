"""Base analyzer classes for command output analysis."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List

from langchain_core.language_models import BaseChatModel
from rich.console import Console

from dump_debugger.llm_router import TaskComplexity, llm_router

console = Console()


class AnalyzerTier(Enum):
    """Analyzer implementation tier."""
    TIER_1 = "tier1"  # Pure code parsing (fastest, no LLM)
    TIER_2 = "tier2"  # Hybrid (code + local LLM)
    TIER_3 = "tier3"  # LLM-heavy (cloud LLM for deep analysis)


@dataclass
class AnalysisResult:
    """Result of command output analysis."""
    
    # Structured data extracted from output
    structured_data: Dict[str, Any]
    
    # Human-readable summary
    summary: str
    
    # Key findings (bullet points)
    findings: List[str]
    
    # Analysis metadata
    metadata: Dict[str, Any]
    
    # Whether analysis was successful
    success: bool = True
    
    # Error message if analysis failed
    error: str | None = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "structured_data": self.structured_data,
            "summary": self.summary,
            "findings": self.findings,
            "metadata": self.metadata,
            "success": self.success,
            "error": self.error,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AnalysisResult":
        """Create from dictionary."""
        return cls(
            structured_data=data.get("structured_data", {}),
            summary=data.get("summary", ""),
            findings=data.get("findings", []),
            metadata=data.get("metadata", {}),
            success=data.get("success", True),
            error=data.get("error"),
        )


class BaseAnalyzer(ABC):
    """Base class for specialized command analyzers."""
    
    # Analyzer metadata (override in subclasses)
    name: str = "base"
    description: str = "Base analyzer"
    tier: AnalyzerTier = AnalyzerTier.TIER_3
    supported_commands: List[str] = []
    
    def __init__(self):
        """Initialize analyzer."""
        self.llm: BaseChatModel | None = None
    
    @abstractmethod
    def can_analyze(self, command: str) -> bool:
        """Check if this analyzer can handle the command.
        
        Args:
            command: Debugger command string
            
        Returns:
            True if analyzer can handle this command
        """
        pass
    
    @abstractmethod
    def analyze(self, command: str, output: str) -> AnalysisResult:
        """Analyze command output.
        
        Args:
            command: Debugger command that was executed
            output: Command output to analyze
            
        Returns:
            Analysis result with structured data and summary
        """
        pass
    
    def get_llm(self, complexity: TaskComplexity = TaskComplexity.MODERATE) -> BaseChatModel:
        """Get appropriate LLM for this analyzer.
        
        Args:
            complexity: Task complexity (used if tiered routing enabled)
            
        Returns:
            LLM instance
        """
        if self.llm is None:
            # Use router to get appropriate LLM based on complexity
            console.print(f"[dim]  → {self.name} analyzer requesting LLM for {complexity.value} task[/dim]")
            self.llm = llm_router.get_llm_for_task(complexity)
        return self.llm
    
    def parse_table(self, output: str, headers: List[str]) -> List[Dict[str, str]]:
        """Parse tabular output into structured data.
        
        Args:
            output: Command output containing table
            headers: Expected column headers
            
        Returns:
            List of dictionaries (one per row)
        """
        rows = []
        lines = output.strip().split('\n')
        
        # Find header row
        header_idx = -1
        for i, line in enumerate(lines):
            if all(h.lower() in line.lower() for h in headers):
                header_idx = i
                break
        
        if header_idx == -1:
            return []
        
        # Parse data rows (skip header and separator)
        for line in lines[header_idx + 1:]:
            # Skip separator lines
            if not line.strip() or set(line.strip()) <= {'-', '=', ' '}:
                continue
            
            # Skip empty or summary lines
            if not any(c.isalnum() for c in line):
                continue
            
            # Simple column splitting (whitespace-separated)
            parts = line.split()
            if len(parts) >= len(headers):
                row = {headers[i]: parts[i] if i < len(parts) else "" for i in range(len(headers))}
                rows.append(row)
        
        return rows
    
    def extract_key_value_pairs(self, output: str) -> Dict[str, str]:
        """Extract key-value pairs from output.
        
        Args:
            output: Command output
            
        Returns:
            Dictionary of key-value pairs
        """
        pairs = {}
        lines = output.strip().split('\n')
        
        for line in lines:
            # Look for "Key: Value" or "Key = Value" patterns
            if ':' in line:
                parts = line.split(':', 1)
                if len(parts) == 2:
                    key = parts[0].strip()
                    value = parts[1].strip()
                    if key and value:
                        pairs[key] = value
            elif '=' in line and '==' not in line:
                parts = line.split('=', 1)
                if len(parts) == 2:
                    key = parts[0].strip()
                    value = parts[1].strip()
                    if key and value:
                        pairs[key] = value
        
        return pairs
    
    def count_occurrences(self, output: str, pattern: str) -> int:
        """Count pattern occurrences in output.
        
        Args:
            output: Command output
            pattern: Pattern to search for
            
        Returns:
            Number of occurrences
        """
        return output.lower().count(pattern.lower())
    
    def estimate_complexity(self, output: str) -> TaskComplexity:
        """Estimate analysis complexity based on output size.
        
        Args:
            output: Command output
            
        Returns:
            Estimated task complexity
        """
        size = len(output)
        
        if size < 10_000:  # < 10KB
            return TaskComplexity.SIMPLE
        elif size < 100_000:  # < 100KB
            return TaskComplexity.MODERATE
        else:  # >= 100KB
            return TaskComplexity.COMPLEX
