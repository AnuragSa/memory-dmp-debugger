"""Tier 2 analyzer for !gcroot command output - memory leak root cause analysis."""

import re
from typing import Any, Dict, List

from dump_debugger.analyzers.base import AnalysisResult, AnalyzerTier, BaseAnalyzer
from dump_debugger.llm_router import TaskComplexity


class GCRootAnalyzer(BaseAnalyzer):
    """Analyzes !gcroot command output to identify memory leak patterns.
    
    Tier 2: Uses code parsing + local LLM for pattern classification.
    
    Detects:
    - Reference chains keeping objects alive
    - Leak patterns (static fields, event handlers, DbContext, timers)
    - Root count and severity assessment
    - Specific object types in chains
    """
    
    name = "gcroot"
    description = "GC root chain analysis for memory leak investigation"
    tier = AnalyzerTier.TIER_2
    supported_commands = ["!gcroot", "!GCRoot"]
    
    def can_analyze(self, command: str) -> bool:
        """Check if this is a gcroot command."""
        cmd_lower = command.lower().strip()
        return cmd_lower.startswith("!gcroot")
    
    def analyze(self, command: str, output: str) -> AnalysisResult:
        """Analyze gcroot output to identify leak patterns.
        
        Args:
            command: The gcroot command
            output: Command output
            
        Returns:
            Analysis result with leak pattern classification
        """
        try:
            # Extract target address from command
            target_address = self._extract_target_address(command)
            
            # Parse reference chains
            chains = self._parse_reference_chains(output)
            
            # Extract root count
            root_count = self._extract_root_count(output)
            
            # Check for common error patterns
            if "not found" in output.lower() or "not in the heap" in output.lower():
                return AnalysisResult(
                    structured_data={
                        "target_address": target_address,
                        "root_count": 0,
                        "chains": [],
                        "error": "Object not found or not in heap"
                    },
                    summary=f"Object {target_address} not found in heap or already collected",
                    findings=[
                        "Object may have already been garbage collected",
                        "Address may be invalid or freed"
                    ],
                    metadata={
                        "analyzer": self.name,
                        "tier": self.tier.value,
                        "command": command
                    },
                    success=True
                )
            
            # Classify leak pattern using local LLM
            leak_pattern = self._classify_leak_pattern(chains, output) if chains else None
            
            # Build findings
            findings = self._build_findings(chains, root_count, leak_pattern)
            
            # Create summary
            summary = self._create_summary(target_address, chains, root_count, leak_pattern)
            
            return AnalysisResult(
                structured_data={
                    "target_address": target_address,
                    "root_count": root_count,
                    "chains": chains,
                    "leak_pattern": leak_pattern,
                    "total_chain_count": len(chains)
                },
                summary=summary,
                findings=findings,
                metadata={
                    "analyzer": self.name,
                    "tier": self.tier.value,
                    "command": command,
                    "pattern_detected": leak_pattern is not None
                },
                success=True
            )
            
        except Exception as e:
            return AnalysisResult(
                structured_data={},
                summary=f"Failed to analyze gcroot output: {str(e)}",
                findings=[],
                metadata={"analyzer": self.name, "error": str(e)},
                success=False,
                error=str(e)
            )
    
    def _extract_target_address(self, command: str) -> str:
        """Extract target object address from command."""
        parts = command.split()
        if len(parts) >= 2:
            return parts[1].strip()
        return "unknown"
    
    def _parse_reference_chains(self, output: str) -> List[Dict[str, Any]]:
        """Parse reference chains from gcroot output.
        
        Returns:
            List of chains, each with thread_id, stack_frames, and object_chain
        """
        chains = []
        current_chain = None
        
        lines = output.split('\n')
        
        for line in lines:
            # Thread marker: "Thread 4aec:"
            thread_match = re.match(r'Thread\s+([0-9a-fA-F]+):', line)
            if thread_match:
                if current_chain:
                    chains.append(current_chain)
                current_chain = {
                    "thread_id": thread_match.group(1),
                    "stack_frames": [],
                    "object_chain": []
                }
                continue
            
            if not current_chain:
                continue
            
            # Stack frame: "    00000066f5cfeab8 00007ff807f5c123 System.Data.Entity..."
            frame_match = re.match(r'\s{4}([0-9a-fA-F]+)\s+([0-9a-fA-F]+)\s+(.+)', line)
            if frame_match:
                current_chain["stack_frames"].append({
                    "rsp": frame_match.group(1),
                    "ip": frame_match.group(2),
                    "method": frame_match.group(3).strip()
                })
                continue
            
            # Object reference: "        ->  000002e9581f4e68 System.Data.Entity.DbContext"
            obj_match = re.match(r'\s+->?\s+([0-9a-fA-F]+)\s+(.+)', line)
            if obj_match:
                current_chain["object_chain"].append({
                    "address": obj_match.group(1),
                    "type": obj_match.group(2).strip()
                })
                continue
            
            # Register reference: "        rbp+30: 00000066f5cfeb00"
            reg_match = re.match(r'\s+(\w+[+-]\d+):\s+([0-9a-fA-F]+)', line)
            if reg_match:
                current_chain["object_chain"].append({
                    "address": reg_match.group(2),
                    "type": f"<register {reg_match.group(1)}>"
                })
        
        if current_chain:
            chains.append(current_chain)
        
        return chains
    
    def _extract_root_count(self, output: str) -> int:
        """Extract unique root count from output."""
        # Look for: "Found 1 unique roots" or "Found 10 unique roots"
        match = re.search(r'Found\s+(\d+)\s+unique\s+roots?', output, re.IGNORECASE)
        if match:
            return int(match.group(1))
        
        # Fallback: count Thread entries
        return len(re.findall(r'Thread\s+[0-9a-fA-F]+:', output))
    
    def _classify_leak_pattern(self, chains: List[Dict[str, Any]], output: str) -> Dict[str, Any] | None:
        """Classify leak pattern using local LLM.
        
        Returns:
            Dictionary with pattern, severity, and fix_suggestion
        """
        if not chains:
            return None
        
        # Build context for LLM
        chain_summaries = []
        for i, chain in enumerate(chains[:3], 1):  # First 3 chains
            obj_types = [obj["type"] for obj in chain["object_chain"]]
            chain_summaries.append(f"Chain {i}: {' → '.join(obj_types)}")
        
        chain_text = "\n".join(chain_summaries)
        
        prompt = f"""Analyze this GC root chain to identify the memory leak pattern.

Reference Chains:
{chain_text}

Total Roots: {len(chains)}

Classify the leak pattern as ONE of:
1. STATIC_FIELD - Object held by static field (lifetime leak)
2. EVENT_HANDLER - Undisposed event subscription
3. ENTITY_FRAMEWORK - DbContext not disposed
4. TIMER - Undisposed Timer object
5. THREAD_LOCAL - Thread-local storage keeping object alive
6. FINALIZER_QUEUE - Object waiting for finalization
7. ASYNC_STATE - Task/async state machine holding reference
8. OTHER - Different pattern

Return JSON:
{{
    "pattern": "PATTERN_NAME",
    "severity": "HIGH|MEDIUM|LOW",
    "reasoning": "Why this pattern was identified",
    "fix_suggestion": "How to fix this specific leak pattern"
}}

Keep reasoning brief (1-2 sentences)."""
        
        try:
            llm = self.get_llm(TaskComplexity.MODERATE)
            from langchain_core.messages import HumanMessage, SystemMessage
            
            response = llm.invoke([
                SystemMessage(content="You are a memory leak expert. Return only valid JSON."),
                HumanMessage(content=prompt)
            ])
            
            import json
            content = response.content.strip()
            
            # Remove markdown code blocks
            if content.startswith('```'):
                content = content.split('```')[1]
                if content.startswith('json'):
                    content = content[4:]
            
            result = json.loads(content.strip())
            return result
            
        except Exception as e:
            # Fallback pattern detection using heuristics
            return self._heuristic_pattern_detection(chains)
    
    def _heuristic_pattern_detection(self, chains: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Fallback pattern detection using code heuristics."""
        # Collect all object types from all chains
        all_types = []
        for chain in chains:
            all_types.extend([obj["type"] for obj in chain["object_chain"]])
        
        all_types_str = " ".join(all_types).lower()
        
        # Pattern detection rules
        if "dbcontext" in all_types_str or "objectcontext" in all_types_str:
            return {
                "pattern": "ENTITY_FRAMEWORK",
                "severity": "HIGH",
                "reasoning": "DbContext/ObjectContext detected in reference chain",
                "fix_suggestion": "Wrap DbContext usage in using() statement or call Dispose() explicitly"
            }
        
        if "timer" in all_types_str:
            return {
                "pattern": "TIMER",
                "severity": "MEDIUM",
                "reasoning": "Timer object in reference chain",
                "fix_suggestion": "Call Timer.Dispose() when no longer needed"
            }
        
        if "eventhandler" in all_types_str or "delegate" in all_types_str:
            return {
                "pattern": "EVENT_HANDLER",
                "severity": "MEDIUM",
                "reasoning": "Event handler/delegate detected",
                "fix_suggestion": "Unsubscribe event handlers before object disposal"
            }
        
        if "task" in all_types_str or "statemachine" in all_types_str:
            return {
                "pattern": "ASYNC_STATE",
                "severity": "MEDIUM",
                "reasoning": "Async Task or state machine in chain",
                "fix_suggestion": "Ensure async operations complete or are properly cancelled"
            }
        
        # Check for static field indicators
        for chain in chains:
            if chain.get("stack_frames"):
                first_frame = chain["stack_frames"][0]["method"]
                if ".cctor" in first_frame or "static" in first_frame.lower():
                    return {
                        "pattern": "STATIC_FIELD",
                        "severity": "HIGH",
                        "reasoning": "Static constructor or static field reference detected",
                        "fix_suggestion": "Review static field lifetime - consider weak references or manual cleanup"
                    }
        
        return {
            "pattern": "OTHER",
            "severity": "MEDIUM",
            "reasoning": f"{len(chains)} reference chain(s) keeping object alive",
            "fix_suggestion": "Analyze reference chain to identify ownership and disposal points"
        }
    
    def _build_findings(
        self, 
        chains: List[Dict[str, Any]], 
        root_count: int,
        leak_pattern: Dict[str, Any] | None
    ) -> List[str]:
        """Build key findings from analysis."""
        findings = []
        
        if root_count == 0:
            findings.append("No GC roots found - object may be eligible for collection")
            return findings
        
        findings.append(f"{root_count} unique root(s) keeping object alive")
        
        if leak_pattern:
            findings.append(f"Leak Pattern: {leak_pattern['pattern']} (Severity: {leak_pattern['severity']})")
            findings.append(f"Cause: {leak_pattern['reasoning']}")
            findings.append(f"Fix: {leak_pattern['fix_suggestion']}")
        
        # Chain depth analysis
        if chains:
            max_depth = max(len(chain["object_chain"]) for chain in chains)
            avg_depth = sum(len(chain["object_chain"]) for chain in chains) / len(chains)
            findings.append(f"Reference chain depth: avg={avg_depth:.1f}, max={max_depth}")
        
        # Thread analysis
        if len(chains) > 1:
            thread_ids = [chain["thread_id"] for chain in chains]
            findings.append(f"Object referenced by {len(set(thread_ids))} thread(s): {', '.join(set(thread_ids))}")
        
        return findings
    
    def _create_summary(
        self,
        target_address: str,
        chains: List[Dict[str, Any]],
        root_count: int,
        leak_pattern: Dict[str, Any] | None
    ) -> str:
        """Create human-readable summary."""
        if root_count == 0:
            return f"Object {target_address} has no GC roots (eligible for collection)"
        
        pattern_desc = ""
        if leak_pattern:
            pattern_desc = f" - {leak_pattern['pattern']} leak pattern detected"
        
        if root_count == 1:
            chain = chains[0] if chains else {}
            chain_length = len(chain.get("object_chain", []))
            return f"Object {target_address} kept alive by 1 root (chain depth: {chain_length}){pattern_desc}"
        else:
            return f"Object {target_address} kept alive by {root_count} roots{pattern_desc} - investigate disposal/cleanup"
