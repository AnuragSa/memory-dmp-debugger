"""Data redaction module for protecting sensitive information before cloud LLM calls.

This module provides comprehensive pattern-based redaction for:
- Connection strings (SQL, MongoDB, Redis, etc.)
- API keys and tokens
- Credentials (passwords, auth headers)
- PII (emails, SSNs, phone numbers, IPs)
- Private keys and certificates
- Internal file paths

Redaction is ALWAYS applied to cloud LLM calls and cannot be disabled.
"""

import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from rich.console import Console

console = Console()


@dataclass
class RedactionPattern:
    """A pattern for detecting and redacting sensitive data.
    
    Attributes:
        name: Human-readable name for this pattern
        pattern: Regex pattern (will be compiled with re.IGNORECASE | re.MULTILINE)
        description: Description of what this pattern matches
        severity: Severity level (info, warning, critical) - for audit logging
    """
    name: str
    pattern: str
    description: str
    severity: str = "warning"
    
    def __post_init__(self):
        """Validate and compile the pattern."""
        try:
            self.compiled = re.compile(self.pattern, re.IGNORECASE | re.MULTILINE)
        except re.error as e:
            raise ValueError(f"Invalid regex pattern '{self.name}': {e}")


class DataRedactor:
    """Redacts sensitive data from text before sending to cloud LLMs.
    
    This class provides comprehensive pattern-based redaction with:
    - Built-in patterns for common secrets
    - Support for custom organization-specific patterns
    - Pattern validation and warnings
    - Optional audit logging
    """
    
    def __init__(self, custom_patterns: list[RedactionPattern] | None = None, 
                 enable_audit: bool = False,
                 audit_log_path: Path | None = None,
                 redaction_placeholder: str = "[REDACTED]",
                 show_values: bool = False):
        """Initialize the data redactor.
        
        Args:
            custom_patterns: Additional organization-specific patterns
            enable_audit: Whether to log redactions to audit file
            audit_log_path: Path to audit log file (required if enable_audit=True)
            redaction_placeholder: Text to replace sensitive data with
        """
        self.redaction_placeholder = redaction_placeholder
        self.enable_audit = enable_audit
        self.audit_log_path = audit_log_path
        self.show_values = show_values
        
        # Stable placeholder mapping for consistent references
        self._placeholder_map = {}  # hash(value) -> placeholder_id
        self._placeholder_counters = {}  # pattern_name -> counter
        
        # Build comprehensive pattern list
        self.patterns = self._get_builtin_patterns()
        
        # Add custom patterns
        if custom_patterns:
            validated_custom = self._validate_patterns(custom_patterns)
            self.patterns.extend(validated_custom)
            console.print(f"[green]✓[/green] Loaded {len(validated_custom)} custom redaction patterns")
        
        # Open audit log if enabled
        self.audit_file = None
        if self.enable_audit:
            if not audit_log_path:
                raise ValueError("audit_log_path required when enable_audit=True")
            self.audit_log_path.parent.mkdir(parents=True, exist_ok=True)
            self.audit_file = open(self.audit_log_path, 'a', encoding='utf-8')
            self._write_audit_header()
    
    def __del__(self):
        """Close audit log file on cleanup."""
        if self.audit_file and not self.audit_file.closed:
            self.audit_file.close()
    
    def _get_builtin_patterns(self) -> list[RedactionPattern]:
        """Get comprehensive built-in redaction patterns.
        
        Returns:
            List of built-in patterns covering common sensitive data types
        """
        return [
            # Connection Strings
            RedactionPattern(
                name="SQLConnectionString",
                pattern=r'(?:Server|Data Source|Initial Catalog|Database)\s*=\s*[^;]+(?:;[^;]*(?:Password|PWD|User ID|UID)\s*=\s*[^;]+)+',
                description="SQL Server connection strings with credentials",
                severity="critical"
            ),
            RedactionPattern(
                name="MongoDBConnectionString",
                pattern=r'mongodb(?:\+srv)?://(?:[^:]+:[^@]+@)?[^/\s]+(?:/[^\s]*)?',
                description="MongoDB connection strings",
                severity="critical"
            ),
            RedactionPattern(
                name="RedisConnectionString",
                pattern=r'redis://(?:[^:]+:[^@]+@)?[^/\s]+(?::\d+)?(?:/\d+)?',
                description="Redis connection strings",
                severity="critical"
            ),
            RedactionPattern(
                name="PostgreSQLConnectionString",
                pattern=r'(?:postgres|postgresql)://(?:[^:]+:[^@]+@)?[^/\s]+(?::\d+)?/[^\s]+',
                description="PostgreSQL connection strings",
                severity="critical"
            ),
            RedactionPattern(
                name="MySQLConnectionString",
                pattern=r'mysql://(?:[^:]+:[^@]+@)?[^/\s]+(?::\d+)?/[^\s]+',
                description="MySQL connection strings",
                severity="critical"
            ),
            
            # API Keys & Tokens
            RedactionPattern(
                name="BearerToken",
                pattern=r'Bearer\s+[A-Za-z0-9\-._~+/]+=*',
                description="Bearer tokens in Authorization headers",
                severity="critical"
            ),
            RedactionPattern(
                name="JWTToken",
                pattern=r'eyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+',
                description="JWT tokens",
                severity="critical"
            ),
            RedactionPattern(
                name="APIKey",
                pattern=r'\b(?:api[_-]?key|apikey|key|token)[\s:=]+["\']?([A-Za-z0-9_\-]{20,})["\']?',
                description="Generic API keys",
                severity="critical"
            ),
            RedactionPattern(
                name="AWSAccessKey",
                pattern=r'\b(AKIA[0-9A-Z]{16})\b',
                description="AWS access key IDs",
                severity="critical"
            ),
            # AWS Secret Key pattern removed - too many false positives with file paths and class names
            RedactionPattern(
                name="AzureConnectionString",
                pattern=r'(?:DefaultEndpointsProtocol|AccountName|AccountKey|EndpointSuffix)\s*=\s*[^;]+(?:;[^;]*){2,}',
                description="Azure storage connection strings",
                severity="critical"
            ),
            RedactionPattern(
                name="GenericSecret",
                pattern=r'\b(?:password|passwd|pwd|secret|token|auth)[\s:=]+["\']?([^\s"\']{8,})["\']?',
                description="Generic passwords and secrets",
                severity="critical"
            ),
            
            # Credentials in URLs
            RedactionPattern(
                name="URLCredentials",
                pattern=r'(?:https?|ftp)://([^:]+):([^@]+)@',
                description="Credentials embedded in URLs",
                severity="critical"
            ),
            
            # PII - Email Addresses
            RedactionPattern(
                name="EmailAddress",
                pattern=r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',
                description="Email addresses",
                severity="warning"
            ),
            
            # PII - Social Security Numbers (with SSA validation rules)
            RedactionPattern(
                name="SSN",
                pattern=r'\b(?!000|666|9\d{2})\d{3}-(?!00)\d{2}-(?!0000)\d{4}\b',
                description="US Social Security Numbers (XXX-XX-XXXX format with SSA validation)",
                severity="critical"
            ),
            RedactionPattern(
                name="SSNNoHyphens",
                pattern=r'\b(?!000)(?!666)(?!9\d{2})\d{3}(?!00)\d{2}(?!0000)\d{4}\b',
                description="US Social Security Numbers (9 digits with SSA validation)",
                severity="critical"
            ),
            
            # PII - Phone Numbers
            RedactionPattern(
                name="PhoneNumberUS",
                pattern=r'\b(?:\+1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b',
                description="US phone numbers",
                severity="warning"
            ),
            
            # PII - Credit Cards (with intelligent validation to avoid false positives)
            # Matches common card prefixes: Visa(4), MC(51-55,2221-2720), Amex(34,37), Discover(6011,65)
            # Avoids matching memory addresses, object IDs, and hex values common in dumps
            RedactionPattern(
                name="CreditCard",
                pattern=r'\b(?:4\d{15}|5[1-5]\d{14}|3[47]\d{13}|6(?:011|5\d{2})\d{12}|4\d{3}[-\s]\d{4}[-\s]\d{4}[-\s]\d{4}|5[1-5]\d{2}[-\s]\d{4}[-\s]\d{4}[-\s]\d{4}|3[47]\d{2}[-\s]\d{6}[-\s]\d{5}|6(?:011|5\d{2})[-\s]\d{4}[-\s]\d{4}[-\s]\d{4})\b',
                description="Credit card numbers with valid prefixes (Visa, MC, Amex, Discover)",
                severity="critical"
            ),
            
            # IP Addresses (internal ranges)
            RedactionPattern(
                name="PrivateIPv4",
                pattern=r'\b(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3})\b',
                description="Private IPv4 addresses",
                severity="info"
            ),
            
            # Private Keys
            RedactionPattern(
                name="PrivateKey",
                pattern=r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----[\s\S]+?-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',
                description="PEM-encoded private keys",
                severity="critical"
            ),
            RedactionPattern(
                name="Certificate",
                pattern=r'-----BEGIN CERTIFICATE-----[\s\S]+?-----END CERTIFICATE-----',
                description="PEM-encoded certificates",
                severity="warning"
            ),
            
            # Windows Credentials
            RedactionPattern(
                name="WindowsCredential",
                pattern=r'(?:domain|username)\\[^\\]+\\(?:password|pwd):[^\s]+',
                description="Windows domain credentials",
                severity="critical"
            ),
            
            # File Paths (internal structure leak)
            RedactionPattern(
                name="InternalPath",
                pattern=r'(?:[A-Z]:|\\\\[^\\]+)\\(?:Users|Documents|Internal|Confidential|Private)\\[^\s]+',
                description="Internal file paths that may reveal structure",
                severity="info"
            ),
            
            # Authorization Headers
            RedactionPattern(
                name="AuthorizationHeader",
                pattern=r'Authorization:\s*(?:Basic|Bearer|Digest)\s+[A-Za-z0-9+/=_-]+',
                description="Authorization HTTP headers",
                severity="critical"
            ),
            
            # X-API-Key Headers
            RedactionPattern(
                name="APIKeyHeader",
                pattern=r'X-API-Key:\s*[A-Za-z0-9_-]{20,}',
                description="X-API-Key HTTP headers",
                severity="critical"
            ),
            
            # Session IDs and Cookies
            RedactionPattern(
                name="SessionID",
                pattern=r'\b(?:session|sessionid|jsessionid|phpsessid|sid)[\s:=]+["\']?([A-Za-z0-9_-]{20,})["\']?',
                description="Session identifiers",
                severity="warning"
            ),
        ]
    
    def _validate_patterns(self, patterns: list[RedactionPattern]) -> list[RedactionPattern]:
        """Validate custom patterns for safety and performance.
        
        Args:
            patterns: List of patterns to validate
            
        Returns:
            List of validated patterns (skips invalid ones with warnings)
        """
        validated = []
        
        for pattern in patterns:
            # Test if pattern compiles
            try:
                test_compiled = re.compile(pattern.pattern, re.IGNORECASE | re.MULTILINE)
            except re.error as e:
                console.print(f"[yellow]⚠ Skipping invalid pattern '{pattern.name}': {e}[/yellow]")
                continue
            
            # Test for overly broad patterns
            test_strings = [
                "normal text without secrets",
                "API_KEY=abc123xyz789",
                "password=secret123",
                "user@example.com",
                "Server=localhost;Database=test;User=admin;Password=pass123"
            ]
            
            match_count = sum(1 for s in test_strings if test_compiled.search(s))
            if match_count >= len(test_strings) * 0.8:  # Matches 80%+ of test strings
                console.print(f"[yellow]⚠ Pattern '{pattern.name}' may be too broad (matches {match_count}/{len(test_strings)} test strings)[/yellow]")
            
            # Check for potentially catastrophic backtracking
            if '.*.*' in pattern.pattern or '.+.+' in pattern.pattern:
                console.print(f"[yellow]⚠ Pattern '{pattern.name}' contains nested quantifiers (.*.*) - may cause performance issues[/yellow]")
            
            validated.append(pattern)
        
        return validated
    
    def _luhn_check(self, card_number: str) -> bool:
        """Validate credit card number using Luhn algorithm.
        
        Args:
            card_number: Credit card number (digits only)
            
        Returns:
            True if passes Luhn checksum, False otherwise
        """
        digits = [int(d) for d in card_number if d.isdigit()]
        if len(digits) < 13 or len(digits) > 19:
            return False
        
        checksum = 0
        for i, digit in enumerate(reversed(digits)):
            if i % 2 == 1:  # Every second digit from right
                digit *= 2
                if digit > 9:
                    digit -= 9
            checksum += digit
        
        return checksum % 10 == 0
    
    def _calculate_context_score(self, text: str, match_pos: int, window_size: int = 50) -> int:
        """Calculate context score for a match based on surrounding text.
        
        Args:
            text: Full text containing the match
            match_pos: Position of the match in text
            window_size: Number of characters to check before and after
            
        Returns:
            Score (positive = likely sensitive, negative = likely benign)
        """
        # Extract window around match
        start = max(0, match_pos - window_size)
        end = min(len(text), match_pos + window_size)
        context = text[start:end].lower()
        
        # High-risk keywords (increase score)
        high_risk_keywords = [
            'password', 'pwd', 'secret', 'token', 'bearer', 'authorization',
            'api_key', 'apikey', 'keyvault', 'sas', 'signature', 'private',
            'ssh', 'certificate', 'client_secret', 'connstr', 'connection',
            'server=', 'uid=', 'user id', 'credential', 'auth', 'key='
        ]
        
        # Low-risk context (decrease score)
        low_risk_keywords = [
            '0x', 'line', 'offset', 'thread', 'stack', 'frame',
            'address', 'pointer', 'handle', 'id', 'count'
        ]
        
        score = 0
        for keyword in high_risk_keywords:
            if keyword in context:
                score += 10
        
        for keyword in low_risk_keywords:
            if keyword in context:
                score -= 5
        
        return score
    
    def _get_stable_placeholder(self, pattern_name: str, matched_value: str, preserve_shape: bool = False) -> str:
        """Get or create a stable placeholder for a matched value.
        
        Args:
            pattern_name: Name of the pattern that matched
            matched_value: The value that was matched
            preserve_shape: If True, include shape info like [last4=1234]
            
        Returns:
            Stable placeholder like 'CC_1' or 'TOKEN_2'
        """
        # Create hash of value for stable mapping
        value_hash = hash(matched_value)
        
        if value_hash in self._placeholder_map:
            return self._placeholder_map[value_hash]
        
        # Get next counter for this pattern type
        if pattern_name not in self._placeholder_counters:
            self._placeholder_counters[pattern_name] = 0
        
        self._placeholder_counters[pattern_name] += 1
        counter = self._placeholder_counters[pattern_name]
        
        # Create placeholder based on pattern type
        if pattern_name == "CreditCard":
            prefix = "CC"
            if preserve_shape and len(matched_value) >= 4:
                last4 = ''.join(c for c in matched_value if c.isdigit())[-4:]
                placeholder = f"{prefix}_{counter}[last4={last4}]"
            else:
                placeholder = f"{prefix}_{counter}"
        elif pattern_name in ["SSN", "SSNNoHyphens"]:
            placeholder = f"SSN_{counter}"
        elif "Token" in pattern_name or "Key" in pattern_name:
            prefix = "TOKEN"
            if preserve_shape:
                placeholder = f"{prefix}_{counter}[len={len(matched_value)}]"
            else:
                placeholder = f"{prefix}_{counter}"
        elif "Email" in pattern_name:
            placeholder = f"EMAIL_{counter}"
        elif "ConnectionString" in pattern_name:
            placeholder = f"CONNSTR_{counter}"
        else:
            # Generic placeholder
            placeholder = f"{pattern_name.upper()}_{counter}"
        
        # Store mapping
        self._placeholder_map[value_hash] = placeholder
        
        return placeholder
    
    def redact_text(self, text: str, context: str = "unknown", command_risk: str = "medium") -> tuple[str, int]:
        """Redact sensitive data from text with intelligent validation and context scoring.
        
        Args:
            text: Text to redact
            context: Context for audit logging (e.g., "investigator_task_1")
            command_risk: Risk level of command ("low", "medium", "high", "critical")
            
        Returns:
            Tuple of (redacted_text, redaction_count)
        """
        if not text:
            return text, 0
        
        redacted = text
        total_redactions = 0
        redactions_by_pattern = {}
        validated_matches = []  # Store (pattern, match, placeholder) tuples
        
        # First pass: find and validate all matches
        for pattern in self.patterns:
            matches = list(pattern.compiled.finditer(text))
            
            for match in matches:
                matched_value = match.group(0)
                should_redact = True
                
                # Apply pattern-specific validation
                if pattern.name == "CreditCard":
                    # Luhn checksum validation
                    digits = ''.join(c for c in matched_value if c.isdigit())
                    if not self._luhn_check(digits):
                        should_redact = False
                        continue
                
                elif pattern.name in ["SSN", "SSNNoHyphens"]:
                    # SSN validation - check for memory dump technical context
                    # In memory dumps, 9-digit numbers are often hash codes, addresses, or counters
                    context_window = text[max(0, match.start()-100):min(len(text), match.end()+100)]
                    context_lower = context_window.lower()
                    
                    # Technical context indicators (these suggest NOT an SSN)
                    technical_indicators = [
                        'method table', 'mt:', 'mt ', 'address', '0x',
                        'hash', 'hashcode', 'count:', 'size:', 'total:',
                        'bytes', 'object', 'instance', 'type:', 'class:',
                        'heap', 'generation', 'syncblk', 'thread id',
                        'handle', 'pointer', 'offset', 'id:', 'tid:'
                    ]
                    
                    # Check if this appears in a technical context
                    if any(indicator in context_lower for indicator in technical_indicators):
                        should_redact = False
                        continue
                    
                    # Check if surrounded by other 9-digit numbers (likely hash codes or addresses)
                    # Look for patterns like: 123456789 234567890 345678901 (multiple 9-digit numbers in a row)
                    surrounding = text[max(0, match.start()-50):min(len(text), match.end()+50)]
                    import re
                    nine_digit_numbers = re.findall(r'\b\d{9}\b', surrounding)
                    if len(nine_digit_numbers) >= 3:  # If 3+ nine-digit numbers nearby, likely technical data
                        should_redact = False
                        continue
                
                # AWS Secret Key validation removed - pattern disabled due to false positives
                
                # Context scoring only applies to generic patterns (not structured PII like CC, SSN)
                # Skip context scoring for: CreditCard, SSN, Email, ConnectionString, PrivateKey, etc.
                skip_context_patterns = {"CreditCard", "SSN", "SSNNoHyphens", "EmailAddress", 
                                       "ConnectionString", "AzureConnectionString", "PrivateKey",
                                       "Certificate", "AWSAccessKey"}  # AWSSecretKey removed
                
                if pattern.name not in skip_context_patterns and command_risk not in ["critical", "high"]:
                    context_score = self._calculate_context_score(text, match.start())
                    
                    # For low/medium risk commands, only redact generic patterns if context suggests sensitive
                    if command_risk == "low" and context_score < 5:
                        should_redact = False
                        continue
                    elif command_risk == "medium" and context_score < 0:
                        should_redact = False
                        continue
                
                if should_redact:
                    # Generate stable placeholder
                    placeholder = self._get_stable_placeholder(
                        pattern.name,
                        matched_value,
                        preserve_shape=(pattern.name == "CreditCard")
                    )
                    validated_matches.append((pattern, match, placeholder, matched_value))
        
        # Second pass: apply redactions with stable placeholders
        # Sort by position (reverse) to avoid offset issues
        validated_matches.sort(key=lambda x: x[1].start(), reverse=True)
        
        for pattern, match, placeholder, matched_value in validated_matches:
            # Replace with stable placeholder
            start, end = match.start(), match.end()
            redacted = redacted[:start] + placeholder + redacted[end:]
            
            total_redactions += 1
            redactions_by_pattern[pattern.name] = redactions_by_pattern.get(pattern.name, 0) + 1
            
            # Log to audit if enabled
            if self.enable_audit:
                self._write_audit_entry(pattern, [match], context, placeholder, matched_value)
        
        # Log summary
        if total_redactions > 0 and self.enable_audit:
            self._write_audit_summary(total_redactions, redactions_by_pattern, context)
        
        return redacted, total_redactions
    
    def _write_audit_header(self):
        """Write header to audit log file."""
        if self.audit_file:
            self.audit_file.write(f"\n{'='*80}\n")
            self.audit_file.write(f"REDACTION AUDIT LOG - Started at {datetime.now().isoformat()}\n")
            self.audit_file.write(f"{'='*80}\n\n")
            self.audit_file.flush()
    
    def _write_audit_entry(self, pattern: RedactionPattern, matches: list[re.Match], context: str, placeholder: str = None, matched_value: str = None):
        """Write individual redaction to audit log.
        
        Args:
            pattern: Pattern that matched
            matches: List of match objects
            context: Context string
            placeholder: Stable placeholder that replaced the value
            matched_value: The actual matched value (for show_values mode)
        """
        if not self.audit_file:
            return
        
        timestamp = datetime.now().isoformat()
        for match in matches:
            entry = (
                f"{timestamp} | REDACTED | {pattern.name} | {pattern.severity.upper()} | "
                f"Position: {match.start()}-{match.end()} | Length: {len(match.group(0))} | "
                f"Context: {context}"
            )
            
            # Add placeholder info
            if placeholder:
                entry += f" | Placeholder: {placeholder}"
            
            # Optionally show the actual matched value (for debugging)
            if self.show_values and matched_value:
                display_value = matched_value[:200]  # Truncate long matches
                entry += f" | VALUE: {repr(display_value)}"
            
            self.audit_file.write(entry + "\n")
        self.audit_file.flush()
    
    def _write_audit_summary(self, total: int, by_pattern: dict[str, int], context: str):
        """Write redaction summary to audit log.
        
        Args:
            total: Total number of redactions
            by_pattern: Dictionary of pattern name -> count
            context: Context string
        """
        if not self.audit_file:
            return
        
        timestamp = datetime.now().isoformat()
        patterns_str = ", ".join(f"{name}={count}" for name, count in by_pattern.items())
        self.audit_file.write(
            f"{timestamp} | SUMMARY | Total: {total} redactions | "
            f"Patterns: {patterns_str} | Context: {context}\n"
        )
        self.audit_file.write("-" * 80 + "\n")
        self.audit_file.flush()


class RedactionEmbeddingsWrapper:
    """Wrapper that applies data redaction before sending text to cloud embedding APIs.
    
    This wrapper intercepts embed_documents() and embed_query() calls, redacts sensitive
    data using the same patterns as chat redaction, and logs redactions to the shared
    audit log if enabled.
    
    SECURITY: This ensures that connection strings, API keys, credentials, and PII
    are not leaked through embedding calls to cloud providers (OpenAI, Azure).
    """
    
    def __init__(self, embeddings, provider_name: str, session_id: str | None = None):
        """Initialize the embeddings wrapper.
        
        Args:
            embeddings: Underlying embeddings instance (OpenAIEmbeddings, AzureOpenAIEmbeddings, etc.)
            provider_name: Provider name for audit logging (e.g., "openai", "azure")
            session_id: Session ID for audit logging (uses current session if not provided)
        """
        self._embeddings = embeddings
        self._provider_name = provider_name
        self._session_id = session_id
        self._total_redactions = 0
    
    def _get_redactor(self) -> DataRedactor:
        """Get or create the global redactor instance.
        
        Uses the shared get_shared_redactor() to ensure the same redactor instance
        is used by both RedactionLLMWrapper (for chat) and RedactionEmbeddingsWrapper
        (for embeddings), sharing the same audit log.
        """
        return get_shared_redactor(session_id=self._session_id)
    
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed a list of documents after redacting sensitive data.
        
        Args:
            texts: List of texts to embed
            
        Returns:
            List of embedding vectors
        """
        redactor = self._get_redactor()
        redacted_texts = []
        total_redactions = 0
        
        for i, text in enumerate(texts):
            redacted_text, redaction_count = redactor.redact_text(
                text,
                context=f"embedding_document_{self._provider_name}_{i}"
            )
            redacted_texts.append(redacted_text)
            total_redactions += redaction_count
        
        self._total_redactions += total_redactions
        
        if total_redactions > 0:
            console.print(
                f"[dim]🔒 Redacted {total_redactions} sensitive item(s) from {len(texts)} document(s) before embedding[/dim]"
            )
        
        return self._embeddings.embed_documents(redacted_texts)
    
    def embed_query(self, text: str) -> list[float]:
        """Embed a query after redacting sensitive data.
        
        Args:
            text: Query text to embed
            
        Returns:
            Embedding vector
        """
        redactor = self._get_redactor()
        redacted_text, redaction_count = redactor.redact_text(
            text,
            context=f"embedding_query_{self._provider_name}"
        )
        
        self._total_redactions += redaction_count
        
        if redaction_count > 0:
            console.print(
                f"[dim]🔒 Redacted {redaction_count} sensitive item(s) from query before embedding[/dim]"
            )
        
        return self._embeddings.embed_query(redacted_text)
    
    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        """Async version of embed_documents with redaction.
        
        Args:
            texts: List of texts to embed
            
        Returns:
            List of embedding vectors
        """
        redactor = self._get_redactor()
        redacted_texts = []
        total_redactions = 0
        
        for i, text in enumerate(texts):
            redacted_text, redaction_count = redactor.redact_text(
                text,
                context=f"embedding_document_{self._provider_name}_{i}"
            )
            redacted_texts.append(redacted_text)
            total_redactions += redaction_count
        
        self._total_redactions += total_redactions
        
        if total_redactions > 0:
            console.print(
                f"[dim]🔒 Redacted {total_redactions} sensitive item(s) from {len(texts)} document(s) before async embedding[/dim]"
            )
        
        return await self._embeddings.aembed_documents(redacted_texts)
    
    async def aembed_query(self, text: str) -> list[float]:
        """Async version of embed_query with redaction.
        
        Args:
            text: Query text to embed
            
        Returns:
            Embedding vector
        """
        redactor = self._get_redactor()
        redacted_text, redaction_count = redactor.redact_text(
            text,
            context=f"embedding_query_{self._provider_name}"
        )
        
        self._total_redactions += redaction_count
        
        if redaction_count > 0:
            console.print(
                f"[dim]🔒 Redacted {redaction_count} sensitive item(s) from query before async embedding[/dim]"
            )
        
        return await self._embeddings.aembed_query(redacted_text)
    
    def __getattr__(self, name: str):
        """Delegate other attribute access to underlying embeddings."""
        return getattr(self._embeddings, name)


# Global redactor instance (shared by RedactionLLMWrapper and RedactionEmbeddingsWrapper)
_redactor: DataRedactor | None = None


def get_shared_redactor(session_id: str | None = None) -> DataRedactor:
    """Get or create the global shared redactor instance.
    
    This function provides a single shared redactor for both LLM and embeddings
    redaction, ensuring consistent patterns and a shared audit log.
    
    Args:
        session_id: Session ID for audit logging (optional, falls back to settings.current_session_id)
        
    Returns:
        DataRedactor instance with audit logging configured if enabled
    """
    global _redactor
    
    # Import settings here to avoid circular import
    from dump_debugger.config import settings
    
    # Always recreate if show_values changed (for debugging session)
    # or if redactor doesn't exist yet
    should_recreate = (
        _redactor is None or 
        (hasattr(_redactor, 'show_values') and _redactor.show_values != settings.show_redacted_values)
    )
    
    if should_recreate:
        # Load custom patterns
        custom_patterns_path = settings.redaction_patterns_path
        custom_patterns = load_custom_patterns(custom_patterns_path)
        
        # Setup audit logging if enabled AND we have a session_id
        audit_log_path = None
        enable_audit = False
        # Use provided session_id or fall back to settings.current_session_id
        session_id_to_use = session_id or settings.current_session_id
        if settings.enable_redaction_audit and session_id_to_use:
            audit_log_path = Path(settings.sessions_base_dir) / session_id_to_use / "redaction_audit.log"
            enable_audit = True
        
        _redactor = DataRedactor(
            custom_patterns=custom_patterns,
            enable_audit=enable_audit,
            audit_log_path=audit_log_path,
            redaction_placeholder="[REDACTED]",
            show_values=settings.show_redacted_values
        )
    return _redactor


def load_custom_patterns(patterns_path: str | Path | None = None) -> list[RedactionPattern]:
    """Load custom redaction patterns from Python file.
    
    Args:
        patterns_path: Path to Python module with CUSTOM_PATTERNS list
                      If None, checks .redaction/custom_patterns.py
    
    Returns:
        List of custom patterns, or empty list if file doesn't exist
    """
    # Determine path
    if patterns_path is None:
        patterns_path = Path(".redaction/custom_patterns.py")
    else:
        patterns_path = Path(patterns_path)
    
    if not patterns_path.exists():
        return []
    
    # Load the module
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("custom_patterns", patterns_path)
        if spec is None or spec.loader is None:
            console.print(f"[yellow]⚠ Could not load custom patterns from {patterns_path}[/yellow]")
            return []
        
        module = importlib.util.module_from_spec(spec)
        sys.modules["custom_patterns"] = module
        spec.loader.exec_module(module)
        
        # Extract CUSTOM_PATTERNS
        if hasattr(module, "CUSTOM_PATTERNS"):
            patterns = module.CUSTOM_PATTERNS
            if isinstance(patterns, list):
                console.print(f"[green]✓[/green] Loaded custom patterns from {patterns_path}")
                return patterns
            else:
                console.print(f"[yellow]⚠ CUSTOM_PATTERNS in {patterns_path} is not a list[/yellow]")
                return []
        else:
            console.print(f"[yellow]⚠ No CUSTOM_PATTERNS found in {patterns_path}[/yellow]")
            return []
    
    except Exception as e:
        console.print(f"[red]✗ Error loading custom patterns from {patterns_path}: {e}[/red]")
        return []
