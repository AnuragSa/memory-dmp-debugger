"""Tier 1 analyzer for !handle command output - Windows handle analysis."""

import re
from collections import Counter
from typing import Any, Dict, List

from dump_debugger.analyzers.base import AnalysisResult, AnalyzerTier, BaseAnalyzer


class HandleAnalyzer(BaseAnalyzer):
    """Analyzes !handle command output.
    
    Tier 1: Pure code parsing for instant analysis.
    
    Extracts:
    - List of handles with values and types
    - Handle type statistics
    - Handle leak detection (excessive handles)
    - Resource usage patterns
    """
    
    name = "handle"
    description = "Windows handle analysis and leak detection"
    tier = AnalyzerTier.TIER_1
    supported_commands = ["!handle"]
    
    # Handle types that commonly indicate issues when excessive
    ISSUE_THRESHOLDS = {
        "Event": 1000,
        "Thread": 500,
        "File": 200,
        "Mutant": 100,  # Mutex
        "Semaphore": 100,
        "Section": 500,  # Memory mapped file sections
        "Key": 100,  # Registry keys
    }
    
    # Handle types to highlight
    INTERESTING_TYPES = {
        "File": "file_handles",
        "Thread": "thread_handles",
        "Event": "synchronization",
        "Mutant": "synchronization",
        "Semaphore": "synchronization",
        "IoCompletion": "io_completion_ports",
        "TpWorkerFactory": "thread_pool",
        "Section": "memory_mapped_files",
        "Key": "registry_handles",
        "Socket": "network_handles",
        "ALPC Port": "inter_process_communication",
    }
    
    def can_analyze(self, command: str) -> bool:
        """Check if this is a handle command."""
        cmd_lower = command.lower().strip()
        return cmd_lower.startswith("!handle")
    
    def analyze(self, command: str, output: str) -> AnalysisResult:
        """Analyze handle command output.
        
        Args:
            command: The handle command
            output: Command output
            
        Returns:
            Analysis result with handle statistics
        """
        try:
            # Parse handles
            handles = self._parse_handles(output)
            
            # Check if empty
            if not handles:
                return AnalysisResult(
                    structured_data={
                        "handle_count": 0,
                        "handles": []
                    },
                    summary="No handles found",
                    findings=["Process may have just started or handles not enumerated"],
                    metadata={
                        "analyzer": self.name,
                        "tier": self.tier.value,
                        "command": command
                    },
                    success=True
                )
            
            # Calculate statistics
            type_stats = self._calculate_type_stats(handles)
            
            # Detect issues
            issues = self._detect_issues(type_stats)
            
            # Detect patterns
            patterns = self._detect_patterns(handles, type_stats)
            
            # Build findings
            findings = self._build_findings(len(handles), type_stats, issues, patterns)
            
            # Create summary
            summary = self._create_summary(len(handles), type_stats, issues)
            
            return AnalysisResult(
                structured_data={
                    "handle_count": len(handles),
                    "handles": handles[:100],  # Limit to first 100 for structured data
                    "type_statistics": type_stats,
                    "issues": issues,
                    "patterns": patterns
                },
                summary=summary,
                findings=findings,
                metadata={
                    "analyzer": self.name,
                    "tier": self.tier.value,
                    "command": command,
                    "has_issues": len(issues) > 0
                },
                success=True
            )
            
        except Exception as e:
            return AnalysisResult(
                structured_data={},
                summary="",
                findings=[],
                metadata={
                    "analyzer": self.name,
                    "tier": self.tier.value,
                    "command": command
                },
                error=f"Failed to analyze handle output: {str(e)}",
                success=False
            )
    
    def _parse_handles(self, output: str) -> List[Dict[str, str]]:
        """Parse handles from output.
        
        Output format:
        Handle 0000000000000004
          Type          Event
        """
        handles = []
        current_handle = None
        
        lines = output.split('\n')
        for line in lines:
            line = line.strip()
            
            # Match handle line: Handle 0000000000000004
            handle_match = re.match(r'Handle\s+([0-9a-fA-F]+)', line)
            if handle_match:
                current_handle = handle_match.group(1)
                continue
            
            # Match type line: Type          Event
            type_match = re.match(r'Type\s+(\S+.*)', line)
            if type_match and current_handle:
                handle_type = type_match.group(1).strip()
                handles.append({
                    "handle": current_handle,
                    "type": handle_type
                })
                current_handle = None
        
        return handles
    
    def _calculate_type_stats(self, handles: List[Dict[str, str]]) -> Dict[str, Any]:
        """Calculate handle type statistics."""
        types = [h["type"] for h in handles]
        type_counts = Counter(types)
        
        # Sort by count descending
        sorted_types = sorted(type_counts.items(), key=lambda x: x[1], reverse=True)
        
        return {
            "total_handles": len(handles),
            "unique_types": len(type_counts),
            "type_counts": dict(type_counts),
            "top_types": sorted_types[:10],
            "all_types": sorted_types
        }
    
    def _detect_issues(self, type_stats: Dict[str, Any]) -> List[str]:
        """Detect potential handle leak issues."""
        issues = []
        
        for handle_type, threshold in self.ISSUE_THRESHOLDS.items():
            count = type_stats["type_counts"].get(handle_type, 0)
            if count > threshold:
                severity = "CRITICAL" if count > threshold * 2 else "WARNING"
                issues.append(f"{severity}: {handle_type} handles excessive ({count} > {threshold})")
        
        # General handle count warning
        if type_stats["total_handles"] > 5000:
            issues.append(f"CRITICAL: Total handle count very high ({type_stats['total_handles']})")
        elif type_stats["total_handles"] > 2000:
            issues.append(f"WARNING: Total handle count elevated ({type_stats['total_handles']})")
        
        return issues
    
    def _detect_patterns(self, handles: List[Dict[str, str]], type_stats: Dict[str, Any]) -> List[str]:
        """Detect notable patterns in handle usage."""
        patterns = []
        
        # Check for specific interesting types
        for handle_type, category in self.INTERESTING_TYPES.items():
            count = type_stats["type_counts"].get(handle_type, 0)
            if count > 0:
                patterns.append(f"{category}: {count} {handle_type} handle(s)")
        
        # Thread pool activity
        tp_count = type_stats["type_counts"].get("TpWorkerFactory", 0)
        if tp_count > 0:
            patterns.append(f"thread_pool_active: {tp_count} worker factory handle(s)")
        
        # IO completion ports
        iocp_count = type_stats["type_counts"].get("IoCompletion", 0)
        if iocp_count > 5:
            patterns.append(f"high_async_io: {iocp_count} IO completion port(s)")
        
        # Many events might indicate synchronization
        event_count = type_stats["type_counts"].get("Event", 0)
        if event_count > 100:
            patterns.append(f"heavy_synchronization: {event_count} Event handles")
        
        return patterns
    
    def _build_findings(
        self,
        total_handles: int,
        type_stats: Dict[str, Any],
        issues: List[str],
        patterns: List[str]
    ) -> List[str]:
        """Build human-readable findings."""
        findings = []
        
        # Basic stats
        findings.append(f"📊 {total_handles:,} total handles, {type_stats['unique_types']} unique types")
        
        # Top handle types
        if type_stats["top_types"]:
            top_5 = type_stats["top_types"][:5]
            top_str = ", ".join([f"{typ}({count})" for typ, count in top_5])
            findings.append(f"🔝 Most common: {top_str}")
        
        # Issues
        if issues:
            findings.append("⚠️ Potential issues:")
            for issue in issues[:5]:  # Limit to 5 most critical
                findings.append(f"  • {issue}")
        
        # Patterns
        if patterns:
            findings.append("🔍 Handle usage patterns:")
            for pattern in patterns[:5]:  # Limit to 5
                findings.append(f"  • {pattern}")
        
        # Recommendations
        if any("CRITICAL" in issue for issue in issues):
            findings.append("💡 Recommendation: Investigate handle leaks - use !htrace or process dumps to track handle allocation")
        elif any("WARNING" in issue for issue in issues):
            findings.append("💡 Recommendation: Monitor handle count trend - may indicate slow leak")
        
        return findings
    
    def _create_summary(
        self,
        total_handles: int,
        type_stats: Dict[str, Any],
        issues: List[str]
    ) -> str:
        """Create concise summary."""
        summary_parts = [f"{total_handles:,} handles"]
        
        # Add top type
        if type_stats["top_types"]:
            top_type, top_count = type_stats["top_types"][0]
            percentage = (top_count / total_handles) * 100
            summary_parts.append(f"{top_type}({top_count}, {percentage:.0f}%)")
        
        # Add critical issue if present
        critical_issues = [i for i in issues if "CRITICAL" in i]
        if critical_issues:
            summary_parts.append(f"⚠️ {len(critical_issues)} critical issue(s)")
        
        return ", ".join(summary_parts)
