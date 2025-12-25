"""Tier 1 analyzer for !do command output - object inspection."""

import re
from typing import Any, Dict, List

from dump_debugger.analyzers.base import AnalysisResult, AnalyzerTier, BaseAnalyzer


class DOAnalyzer(BaseAnalyzer):
    """Analyzes !do (dump object) command output.
    
    Tier 1: Pure code parsing for instant analysis.
    
    Extracts:
    - Object type and metadata (MethodTable, EEClass, Size)
    - All field values (including null detection)
    - String contents
    - Array elements
    - Object state indicators
    """
    
    name = "do"
    description = "Object inspection and field extraction"
    tier = AnalyzerTier.TIER_1
    supported_commands = ["!do", "!DumpObj"]
    
    # Known interesting types to flag
    INTERESTING_TYPES = {
        "Exception": "exception_object",
        "SqlConnection": "database_connection",
        "SqlCommand": "database_command",
        "Task": "async_task",
        "HttpClient": "http_client",
        "FileStream": "file_handle",
        "Timer": "timer_object",
        "Thread": "thread_object",
        "DbContext": "entity_framework_context"
    }
    
    def can_analyze(self, command: str) -> bool:
        """Check if this is a do/dumpobj command."""
        cmd_lower = command.lower().strip()
        return cmd_lower.startswith("!do") or cmd_lower.startswith("!dumpobj")
    
    def analyze(self, command: str, output: str) -> AnalysisResult:
        """Analyze do command output.
        
        Args:
            command: The do command
            output: Command output
            
        Returns:
            Analysis result with object structure
        """
        try:
            # Extract target address from command
            target_address = self._extract_target_address(command)
            
            # Parse object metadata
            metadata = self._parse_object_metadata(output)
            
            # Parse fields
            fields = self._parse_fields(output)
            
            # Extract strings if present
            string_content = self._extract_string_content(output)
            
            # Extract array info if present
            array_info = self._extract_array_info(output)
            
            # Check for error conditions
            if "invalid" in output.lower() or "not found" in output.lower():
                return AnalysisResult(
                    structured_data={
                        "target_address": target_address,
                        "error": "Object not found or invalid address"
                    },
                    summary=f"Object {target_address} not found or invalid",
                    findings=["Address may be invalid, freed, or corrupted"],
                    metadata={
                        "analyzer": self.name,
                        "tier": self.tier.value,
                        "command": command
                    },
                    success=True
                )
            
            # Detect interesting patterns
            object_category = self._categorize_object(metadata.get("type", ""))
            suspicious_patterns = self._detect_suspicious_patterns(metadata, fields)
            
            # Build findings
            findings = self._build_findings(metadata, fields, string_content, array_info, suspicious_patterns)
            
            # Create summary
            summary = self._create_summary(target_address, metadata, fields, object_category)
            
            return AnalysisResult(
                structured_data={
                    "target_address": target_address,
                    "metadata": metadata,
                    "fields": fields,
                    "string_content": string_content,
                    "array_info": array_info,
                    "object_category": object_category,
                    "suspicious_patterns": suspicious_patterns
                },
                summary=summary,
                findings=findings,
                metadata={
                    "analyzer": self.name,
                    "tier": self.tier.value,
                    "command": command,
                    "object_type": metadata.get("type", "unknown"),
                    "has_issues": len(suspicious_patterns) > 0
                },
                success=True
            )
            
        except Exception as e:
            return AnalysisResult(
                structured_data={},
                summary=f"Failed to analyze !do output: {str(e)}",
                findings=[],
                metadata={"analyzer": self.name, "error": str(e)},
                success=False,
                error=str(e)
            )
    
    def _extract_target_address(self, command: str) -> str:
        """Extract target address from command."""
        parts = command.split()
        if len(parts) >= 2:
            return parts[1].strip()
        return "unknown"
    
    def _parse_object_metadata(self, output: str) -> Dict[str, Any]:
        """Parse object metadata (Name, MethodTable, EEClass, Size)."""
        metadata = {}
        
        # Name: System.Data.SqlClient.SqlConnection
        name_match = re.search(r'Name:\s+(.+)', output)
        if name_match:
            metadata["type"] = name_match.group(1).strip()
        
        # MethodTable: 00007ff8082dea10
        mt_match = re.search(r'MethodTable:\s+([0-9a-fA-F]+)', output)
        if mt_match:
            metadata["method_table"] = mt_match.group(1)
        
        # EEClass: 00007ff808145678
        ee_match = re.search(r'EEClass:\s+([0-9a-fA-F]+)', output)
        if ee_match:
            metadata["ee_class"] = ee_match.group(1)
        
        # Size: 120(0x78) bytes
        size_match = re.search(r'Size:\s+(\d+)\(0x[0-9a-fA-F]+\)\s+bytes', output)
        if size_match:
            metadata["size_bytes"] = int(size_match.group(1))
        
        # GC generation (if present)
        gen_match = re.search(r'GC Generation:\s+(\d+)', output)
        if gen_match:
            metadata["gc_generation"] = int(gen_match.group(1))
        
        return metadata
    
    def _parse_fields(self, output: str) -> List[Dict[str, Any]]:
        """Parse object fields.
        
        Field format:
        MT    Field   Offset    Type VT     Attr    Value Name
        00007ff8... 4000001  8  ...String  0 instance 000002e9... _connectionString
        """
        fields = []
        
        # Find Fields section
        lines = output.split('\n')
        in_fields_section = False
        
        for line in lines:
            # Check for Fields header
            if 'MT' in line and 'Field' in line and 'Name' in line:
                in_fields_section = True
                continue
            
            if not in_fields_section:
                continue
            
            # Skip empty lines
            if not line.strip():
                continue
            
            # Parse field line
            # Pattern: MT(hex) FieldID(hex) Offset(dec) Type(text) VT(0/1) Attr(instance/static) Value(hex) Name(text)
            field_match = re.match(
                r'\s*([0-9a-fA-F]+)\s+([0-9a-fA-F]+)\s+(\d+)\s+(.+?)\s+(\d+)\s+(instance|static)\s+([0-9a-fA-F]+)\s+(.+)',
                line
            )
            
            if field_match:
                field_type = field_match.group(4).strip()
                field_value = field_match.group(7)
                field_name = field_match.group(8).strip()
                
                fields.append({
                    "name": field_name,
                    "type": field_type,
                    "value": field_value,
                    "is_null": field_value == "0000000000000000" or field_value == "00000000",
                    "is_static": field_match.group(6) == "static",
                    "offset": int(field_match.group(3))
                })
        
        return fields
    
    def _extract_string_content(self, output: str) -> str | None:
        """Extract string content if object is a string."""
        # String: "Connection string value here"
        string_match = re.search(r'String:\s+(.+)', output)
        if string_match:
            return string_match.group(1).strip().strip('"')
        return None
    
    def _extract_array_info(self, output: str) -> Dict[str, Any] | None:
        """Extract array information if object is an array."""
        # Array: Rank 1, Number of elements 10, Type System.String[]
        array_match = re.search(r'Array:\s+Rank\s+(\d+),\s+Number of elements\s+(\d+)', output)
        if array_match:
            return {
                "rank": int(array_match.group(1)),
                "length": int(array_match.group(2))
            }
        return None
    
    def _categorize_object(self, type_name: str) -> str | None:
        """Categorize object by type."""
        for keyword, category in self.INTERESTING_TYPES.items():
            if keyword.lower() in type_name.lower():
                return category
        return None
    
    def _detect_suspicious_patterns(
        self, 
        metadata: Dict[str, Any], 
        fields: List[Dict[str, Any]]
    ) -> List[str]:
        """Detect suspicious patterns in object state."""
        patterns = []
        
        # Count null fields
        null_fields = [f for f in fields if f["is_null"]]
        if len(null_fields) > len(fields) * 0.5 and len(fields) > 2:
            patterns.append(f"high_null_ratio:{len(null_fields)}/{len(fields)}")
        
        # Large object (> 10KB)
        size = metadata.get("size_bytes", 0)
        if size > 10240:
            patterns.append(f"large_object:{size}_bytes")
        
        # Check for specific field patterns
        field_names = [f["name"].lower() for f in fields]
        
        # Connection/resource fields that should not be null
        critical_fields = {
            "_connectionstring": "database connection string missing",
            "_state": "object state field null",
            "_disposed": "disposal tracking field null"
        }
        
        for field in fields:
            fname = field["name"].lower()
            if fname in critical_fields and field["is_null"]:
                patterns.append(f"critical_null_field:{field['name']}")
        
        return patterns
    
    def _build_findings(
        self,
        metadata: Dict[str, Any],
        fields: List[Dict[str, Any]],
        string_content: str | None,
        array_info: Dict[str, Any] | None,
        suspicious_patterns: List[str]
    ) -> List[str]:
        """Build key findings."""
        findings = []
        
        # Basic info
        obj_type = metadata.get("type", "unknown")
        size = metadata.get("size_bytes", 0)
        findings.append(f"Object type: {obj_type}")
        findings.append(f"Size: {size} bytes ({size / 1024:.2f} KB)" if size > 1024 else f"Size: {size} bytes")
        
        # Field statistics
        if fields:
            null_count = sum(1 for f in fields if f["is_null"])
            static_count = sum(1 for f in fields if f["is_static"])
            findings.append(f"Fields: {len(fields)} total, {null_count} null, {static_count} static")
        
        # String content
        if string_content:
            preview = string_content[:50] + "..." if len(string_content) > 50 else string_content
            findings.append(f"String value: \"{preview}\"")
        
        # Array info
        if array_info:
            findings.append(f"Array: {array_info['length']} elements, rank {array_info['rank']}")
        
        # Suspicious patterns
        for pattern in suspicious_patterns:
            if pattern.startswith("high_null_ratio"):
                findings.append(f"⚠ {pattern.split(':')[1]} fields are null - possible initialization issue")
            elif pattern.startswith("large_object"):
                findings.append(f"⚠ Large object size - potential memory concern")
            elif pattern.startswith("critical_null_field"):
                field_name = pattern.split(':')[1]
                findings.append(f"⚠ Critical field '{field_name}' is null")
        
        # GC generation
        gen = metadata.get("gc_generation")
        if gen is not None:
            findings.append(f"GC Generation {gen}" + (" (long-lived object)" if gen == 2 else ""))
        
        return findings
    
    def _create_summary(
        self,
        target_address: str,
        metadata: Dict[str, Any],
        fields: List[Dict[str, Any]],
        object_category: str | None
    ) -> str:
        """Create human-readable summary."""
        obj_type = metadata.get("type", "unknown")
        size = metadata.get("size_bytes", 0)
        field_count = len(fields)
        
        category_desc = ""
        if object_category:
            category_desc = f" ({object_category.replace('_', ' ')})"
        
        return f"{obj_type}{category_desc} at {target_address}: {size} bytes, {field_count} fields"
