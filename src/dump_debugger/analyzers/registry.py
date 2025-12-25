"""Registry for specialized command analyzers."""

from typing import Dict, List, Type

from dump_debugger.analyzers.base import BaseAnalyzer


class AnalyzerRegistry:
    """Registry for command analyzers."""
    
    def __init__(self):
        """Initialize the registry."""
        self._analyzers: List[BaseAnalyzer] = []
        self._command_cache: Dict[str, BaseAnalyzer] = {}
    
    def register(self, analyzer_class: Type[BaseAnalyzer]):
        """Register an analyzer class.
        
        Args:
            analyzer_class: Analyzer class to register
        """
        analyzer = analyzer_class()
        self._analyzers.append(analyzer)
        
        # Sort by tier (Tier 1 first, then Tier 2, then Tier 3)
        # This ensures we try faster analyzers first
        self._analyzers.sort(key=lambda a: a.tier.value)
    
    def get_analyzer(self, command: str) -> BaseAnalyzer | None:
        """Get appropriate analyzer for command.
        
        Args:
            command: Debugger command string
            
        Returns:
            Analyzer instance or None if no analyzer available
        """
        # Check cache first
        if command in self._command_cache:
            return self._command_cache[command]
        
        # Find first analyzer that can handle this command
        for analyzer in self._analyzers:
            if analyzer.can_analyze(command):
                self._command_cache[command] = analyzer
                return analyzer
        
        # No specialized analyzer found
        return None
    
    def list_analyzers(self) -> List[Dict[str, str]]:
        """List all registered analyzers.
        
        Returns:
            List of analyzer metadata
        """
        return [
            {
                "name": a.name,
                "description": a.description,
                "tier": a.tier.value,
                "commands": ", ".join(a.supported_commands),
            }
            for a in self._analyzers
        ]
    
    def clear_cache(self):
        """Clear the command-to-analyzer cache."""
        self._command_cache.clear()


# Global registry instance
analyzer_registry = AnalyzerRegistry()


def get_analyzer(command: str) -> BaseAnalyzer | None:
    """Get appropriate analyzer for command (convenience function).
    
    Args:
        command: Debugger command string
        
    Returns:
        Analyzer instance or None
    """
    return analyzer_registry.get_analyzer(command)
