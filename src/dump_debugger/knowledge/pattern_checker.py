"""Pattern checker for known common issues."""

import json
from pathlib import Path

import numpy as np
from rich.console import Console

console = Console()


class PatternChecker:
    """Checks for known common patterns using semantic search.
    
    Uses embeddings for semantic similarity matching instead of keyword matching.
    Embeddings are computed once per session and cached.
    """
    
    def __init__(self, patterns_file: Path = None):
        """Initialize pattern checker.
        
        Args:
            patterns_file: Path to patterns JSON file. Defaults to bundled patterns.
        """
        if patterns_file is None:
            patterns_file = Path(__file__).parent / "known_patterns.json"
        
        self.patterns = self._load_patterns(patterns_file)
        self.embeddings_model = None  # Lazy load
        self.pattern_embeddings = None  # Cached embeddings
    
    def _load_patterns(self, patterns_file: Path) -> list[dict]:
        """Load patterns from JSON file.
        
        Args:
            patterns_file: Path to patterns JSON
            
        Returns:
            List of pattern dictionaries
        """
        try:
            with open(patterns_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data.get('patterns', [])
        except Exception as e:
            console.print(f"[yellow]⚠ Could not load patterns: {e}[/yellow]")
            return []
    
    def check_patterns(self, issue_description: str) -> list[dict]:
        """Check if the issue matches any known patterns using semantic search.
        
        Args:
            issue_description: User's description of the issue
            
        Returns:
            List of matching patterns, sorted by relevance (semantic similarity)
        """
        if not self.patterns:
            return []
        
        # Check for local-only mode - use keyword fallback directly
        from dump_debugger.config import settings
        if settings.local_only_mode:
            console.print("[dim]🔒 LOCAL-ONLY MODE: Using keyword matching for patterns[/dim]")
            return self._keyword_fallback(issue_description)
        
        try:
            # Lazy load embeddings model
            if self.embeddings_model is None:
                from dump_debugger.llm import get_embeddings
                console.print("[dim]🔍 Loading embeddings model for pattern matching...[/dim]")
                self.embeddings_model = get_embeddings()
            
            # Compute pattern embeddings if not cached
            if self.pattern_embeddings is None:
                console.print("[dim]🔍 Computing pattern embeddings (one-time)...[/dim]")
                pattern_texts = [
                    f"{p['name']}. {p['symptoms']}. {p['root_cause']}" 
                    for p in self.patterns
                ]
                self.pattern_embeddings = self.embeddings_model.embed_documents(pattern_texts)
            
            # Embed query
            query_embedding = self.embeddings_model.embed_query(issue_description)
            
            # Compute cosine similarity for all patterns
            matches = []
            for i, pattern in enumerate(self.patterns):
                similarity = self._cosine_similarity(query_embedding, self.pattern_embeddings[i])
                
                # Only include if similarity is above threshold
                if similarity > 0.3:  # Lower threshold to catch more matches
                    matches.append({
                        'pattern': pattern,
                        'match_score': float(similarity),
                        'confidence_boost': pattern.get('confidence_boost', 0.2)
                    })
            
            # Sort by similarity descending
            matches.sort(key=lambda x: x['match_score'], reverse=True)
            
            return matches
            
        except Exception as e:
            # If semantic search fails, fall back to keyword matching
            # (This includes Azure without embeddings deployment configured)
            return self._keyword_fallback(issue_description)
    
    def _cosine_similarity(self, vec1: list[float], vec2: list[float]) -> float:
        """Calculate cosine similarity between two vectors.
        
        Args:
            vec1: First vector
            vec2: Second vector
            
        Returns:
            Cosine similarity (0.0 to 1.0)
        """
        vec1 = np.array(vec1)
        vec2 = np.array(vec2)
        return np.dot(vec1, vec2) / (np.linalg.norm(vec1) * np.linalg.norm(vec2))
    
    def _keyword_fallback(self, issue_description: str) -> list[dict]:
        """Fallback to keyword matching if semantic search fails.
        
        Args:
            issue_description: User's issue description
            
        Returns:
            List of matching patterns using keyword matching
        """
        matches = []
        issue_lower = issue_description.lower()
        
        for pattern in self.patterns:
            score = self._calculate_match_score(pattern, issue_lower)
            if score > 0:
                matches.append({
                    'pattern': pattern,
                    'match_score': score,
                    'confidence_boost': pattern.get('confidence_boost', 0.2)
                })
        
        # Sort by match score descending
        matches.sort(key=lambda x: x['match_score'], reverse=True)
        
        return matches
    
    def _calculate_match_score(self, pattern: dict, issue_description: str) -> float:
        """Calculate how well a pattern matches the issue description.
        
        Args:
            pattern: Pattern dictionary
            issue_description: User's issue description (lowercased)
            
        Returns:
            Match score (0.0 to 1.0)
        """
        score = 0.0
        
        # Check symptoms
        symptoms = pattern.get('symptoms', '').lower()
        symptom_keywords = self._extract_keywords(symptoms)
        
        for keyword in symptom_keywords:
            if keyword in issue_description:
                score += 0.3
        
        # Check pattern name
        name_keywords = self._extract_keywords(pattern.get('name', '').lower())
        for keyword in name_keywords:
            if keyword in issue_description:
                score += 0.2
        
        # Check source
        source_keywords = self._extract_keywords(pattern.get('source', '').lower())
        for keyword in source_keywords:
            if keyword in issue_description:
                score += 0.15
        
        # Check severity alignment with issue urgency
        severity = pattern.get('severity', 'MEDIUM')
        urgency_words = ['critical', 'urgent', 'production down', 'outage', 'crash']
        if severity in ['CRITICAL', 'HIGH'] and any(word in issue_description for word in urgency_words):
            score += 0.1
        
        return min(score, 1.0)  # Cap at 1.0
    
    def _extract_keywords(self, text: str) -> list[str]:
        """Extract meaningful keywords from text.
        
        Args:
            text: Text to extract keywords from
            
        Returns:
            List of keywords
        """
        # Remove common stop words
        stop_words = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 
                      'of', 'with', 'by', 'from', 'as', 'is', 'was', 'are', 'were', 'been',
                      'be', 'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would',
                      'should', 'could', 'may', 'might', 'must', 'can'}
        
        words = text.split()
        keywords = [w.strip('.,;:!?()[]{}') for w in words if len(w) > 3 and w not in stop_words]
        return keywords
    
    def format_pattern_hints(self, matches: list[dict], max_patterns: int = 3) -> str:
        """Format pattern matches as hints for hypothesis formation.
        
        Args:
            matches: List of pattern matches from check_patterns
            max_patterns: Maximum number of patterns to include
            
        Returns:
            Formatted string with pattern hints
        """
        if not matches:
            return ""
        
        hints = ["KNOWN PATTERN HINTS (check these common issues first):"]
        
        for i, match in enumerate(matches[:max_patterns], 1):
            pattern = match['pattern']
            score = match['match_score']
            
            hints.append(f"\n{i}. {pattern['name']} (relevance: {score:.0%})")
            hints.append(f"   Symptoms: {pattern['symptoms']}")
            hints.append(f"   Root Cause: {pattern['root_cause']}")
            # investigation_focus is a string in JSON
            focus = pattern.get('investigation_focus', '')
            if focus:
                hints.append(f"   Investigation Focus: {focus}")
            hints.append(f"   Severity: {pattern['severity']}")
        
        hints.append("\nConsider these patterns when forming your hypothesis.")
        
        return "\n".join(hints)
