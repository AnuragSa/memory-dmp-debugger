"""Domain expert agent for pattern assessment using LLM."""

import json
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from rich.console import Console

from dump_debugger.llm import get_llm

console = Console()


class DomainExpertAgent:
    """
    LLM-based domain expert for assessing memory dump patterns.
    
    Provides industry context, severity assessments, and causal reasoning
    for observed patterns based on best practices and production experience.
    """
    
    def __init__(self):
        # Use low temperature for consistent assessments
        self.llm = get_llm(temperature=0.2)
        self.model_name = "cloud-llm"  # Will be populated from actual model
    
    def assess_pattern(self, pattern_type: str, params: dict, 
                      application_context: str = "") -> dict:
        """
        Assess a pattern and provide expert opinion.
        
        Args:
            pattern_type: Type of pattern (e.g., 'ef_query_cache')
            params: Pattern parameters (e.g., {'size_mb': 135})
            application_context: Optional context about the application
            
        Returns:
            Assessment dict with severity, reasoning, impact, etc.
        """
        prompt = self._build_prompt(pattern_type, params, application_context)
        
        try:
            response = self.llm.invoke([
                SystemMessage(content="You are a senior performance engineering consultant with 20+ years experience in .NET, Entity Framework, SQL Server, and production system diagnostics. Provide DECISIVE assessments based on industry standards. Return ONLY valid JSON."),
                HumanMessage(content=prompt)
            ])
            
            # Parse response
            content = response.content.strip()
            
            # Remove markdown code blocks if present
            if content.startswith('```'):
                parts = content.split('```')
                if len(parts) >= 2:
                    content = parts[1]
                    if content.startswith('json'):
                        content = content[4:]
            
            assessment = json.loads(content.strip())
            
            # Validate required fields
            required_fields = ['severity', 'confidence']
            for field in required_fields:
                if field not in assessment:
                    assessment[field] = 'medium'
            
            return assessment
            
        except json.JSONDecodeError as e:
            console.print(f"[yellow]⚠ Failed to parse domain expert response: {e}[/yellow]")
            return self._get_fallback_assessment(pattern_type, params)
        except Exception as e:
            console.print(f"[yellow]⚠ Domain expert error: {e}[/yellow]")
            return self._get_fallback_assessment(pattern_type, params)
    
    def _build_prompt(self, pattern_type: str, params: dict, context: str) -> str:
        """Build assessment prompt based on pattern type."""
        
        base_prompt = f"""You are assessing a pattern from a .NET memory dump analysis.

PATTERN TYPE: {pattern_type}
OBSERVED VALUES: {json.dumps(params, indent=2)}
{f"APPLICATION CONTEXT: {context}" if context else ""}

Your job is to:
1. State what range is NORMAL for production .NET applications
2. Assess the SEVERITY if this value exceeds normal
3. Explain WHY it causes problems (causal reasoning, not speculation)
4. Predict EXPECTED IMPACT with quantitative estimates where possible
5. Provide CONFIDENCE in your assessment

Be DECISIVE based on industry standards. If something exceeds normal thresholds by 2-3x, 
state clearly that it WILL cause problems, not "might" or "could".

Return ONLY valid JSON in this format:
{{
  "normal_range": "String describing typical range for production systems",
  "severity": "critical|high|medium|low",
  "severity_reasoning": "Why this specific value is concerning",
  "why_problematic": "Technical explanation of WHY this causes issues",
  "expected_impact": "Quantitative prediction of impact (e.g., '300ms GC pauses every 50 requests')",
  "causal_chain": ["Step 1 in the problem", "Step 2", "Step 3"],
  "confidence": "high|medium|low",
  "industry_baseline": "What Fortune 500/.NET production apps typically show"
}}

"""
        
        # Add pattern-specific guidance
        if pattern_type == 'ef_query_cache':
            base_prompt += """
SPECIFIC GUIDANCE FOR EF QUERY CACHE:
- Typical production apps: 10-50MB query cache
- Above 100MB: High severity - causes Gen2 GC pressure
- Cache entries are never evicted - unbounded growth
- Each OData $select/$expand variation creates new entry
- Large cache in Gen2 triggers full GC collections
"""
        
        elif pattern_type == 'dbcontext_count':
            base_prompt += """
SPECIFIC GUIDANCE FOR DBCONTEXT COUNT:
- Typical production apps: <100 DbContext instances at any time
- Above 1000: Indicates missing disposal or pooling
- DbContext disposal through finalizers delays cleanup
- Each context holds EF metadata and query cache entries
"""
        
        elif pattern_type == 'thread_count':
            base_prompt += """
SPECIFIC GUIDANCE FOR THREAD COUNT:
- Typical ASP.NET apps: 20-50 threads
- Dead threads indicate thread pool exhaustion or crashes
- High dead thread count suggests unhandled exceptions
"""
        
        elif pattern_type == 'finalizer_queue':
            base_prompt += """
SPECIFIC GUIDANCE FOR FINALIZER QUEUE:
- Typical apps: <100 objects in finalizer queue
- Above 10,000: Indicates resource disposal issues
- Objects with finalizers delay GC collection
- Deep queue causes Gen2 promotion and memory pressure
"""
        
        return base_prompt
    
    def _get_fallback_assessment(self, pattern_type: str, params: dict) -> dict:
        """Provide conservative fallback assessment when LLM fails."""
        return {
            'normal_range': 'Unable to determine',
            'severity': 'medium',
            'severity_reasoning': 'LLM assessment failed, using conservative estimate',
            'why_problematic': f'Pattern {pattern_type} detected with params {params}',
            'expected_impact': 'Impact assessment unavailable',
            'causal_chain': ['Assessment generation failed'],
            'confidence': 'low',
            'industry_baseline': 'Baseline unavailable'
        }
