"""Example custom redaction patterns for organization-specific sensitive data.

Copy this file to custom_patterns.py and add your organization's specific patterns.
The custom_patterns.py file is in .gitignore to keep your patterns private.

USAGE:
1. Copy: cp example_patterns.py custom_patterns.py
2. Edit custom_patterns.py with your patterns
3. The tool will automatically load them at startup

PATTERN STRUCTURE:
    RedactionPattern(
        name="UniqueName",
        pattern=r"regex_pattern_here",
        description="What this pattern matches",
        severity="critical"  # or "warning" or "info"
    )

TESTING YOUR PATTERNS:
    dump-debugger test-patterns sample.txt
    dump-debugger test-patterns sample.txt --pattern-name YourPatternName
"""

from dump_debugger.security.redactor import RedactionPattern

# Example: Custom Social Security Number field names
# Many organizations use different field names for SSN
CUSTOM_PATTERNS = [
    # Example 1: SSN with different field names
    RedactionPattern(
        name="CustomSSN",
        pattern=r'\b(SSN|SocSecNum|social_security|soc_sec_number)\s*[:=]\s*\d{3}-?\d{2}-?\d{4}\b',
        description="Organization-specific SSN field names",
        severity="critical"
    ),
    
    # Example 2: Internal customer identifier
    RedactionPattern(
        name="CustomerID",
        pattern=r'\bCUST-\d{8,10}\b',
        description="Internal customer ID format (CUST-12345678)",
        severity="warning"
    ),
    
    # Example 3: Employee ID
    RedactionPattern(
        name="EmployeeID",
        pattern=r'\b(?:EMP|EMPID|EmployeeNumber)\s*[:=]\s*[A-Z]{2}\d{6}\b',
        description="Employee identifiers (XX123456 format)",
        severity="warning"
    ),
    
    # Example 4: Internal project codes
    RedactionPattern(
        name="ProjectCode",
        pattern=r'\b(?:PROJ|PROJECT)-[A-Z]{3,4}-\d{4}\b',
        description="Internal project codes (PROJ-ABC-1234)",
        severity="info"
    ),
    
    # Example 5: Custom database connection string pattern
    RedactionPattern(
        name="InternalDBConnection",
        pattern=r'(?:internal_db|prod_db|staging_db)://[^\s]+',
        description="Internal database connection strings",
        severity="critical"
    ),
    
    # Example 6: API keys with company prefix
    RedactionPattern(
        name="CompanyAPIKey",
        pattern=r'\b(?:ACME|MYCOMPANY)_[A-Za-z0-9_-]{32,}\b',
        description="Company-prefixed API keys",
        severity="critical"
    ),
    
    # Example 7: Internal server hostnames
    RedactionPattern(
        name="InternalHostname",
        pattern=r'\b(?:prod|staging|dev|qa)-(?:sql|web|api|cache)-\d{2}\.(?:internal|local|corp)\b',
        description="Internal server hostnames",
        severity="info"
    ),
    
    # Example 8: Proprietary account numbers
    RedactionPattern(
        name="AccountNumber",
        pattern=r'\b(?:ACCT|Account)\s*[:=#]\s*[A-Z]{2}\d{10,12}\b',
        description="Proprietary account number format",
        severity="warning"
    ),
]

# TIPS FOR CREATING PATTERNS:
#
# 1. TEST THOROUGHLY: Use `dump-debugger test-patterns` to validate
#
# 2. BE SPECIFIC: Avoid overly broad patterns that match normal text
#    BAD:  r'\b\d+\b'  (matches ALL numbers)
#    GOOD: r'\bSSN:\s*\d{3}-\d{2}-\d{4}\b'  (matches specific format)
#
# 3. USE WORD BOUNDARIES: \b prevents partial matches
#    r'\bpassword\b' matches "password" but not "passworded"
#
# 4. CASE INSENSITIVE: Patterns are automatically case-insensitive
#    r'api[_-]?key' matches: API_KEY, api-key, ApiKey, etc.
#
# 5. ESCAPE SPECIAL CHARS: Use raw strings (r"...") and escape: . * + ? [ ] ( ) { } ^ $ | \
#    r'\$\d+\.\d{2}' matches: $123.45
#
# 6. TEST WITH REAL DATA: Use anonymized samples from your dumps
#
# 7. START CONSERVATIVE: Better to redact more than less
#
# 8. DOCUMENT WELL: Future you will thank present you

# COMMON REGEX PATTERNS:
#
# \b         Word boundary (start/end of word)
# \d         Any digit (0-9)
# \d{3}      Exactly 3 digits
# \d{3,5}    Between 3 and 5 digits
# [A-Z]      Any uppercase letter
# [A-Za-z]   Any letter (upper or lower)
# [A-Za-z0-9_-]  Letters, digits, underscore, hyphen
# \s         Any whitespace (space, tab, newline)
# \s*        Zero or more whitespace
# \s+        One or more whitespace
# [:=]       Either colon or equals
# (?:...)    Non-capturing group
# |          OR operator
# .          Any character (except newline)
# .*         Zero or more of any character
# .+         One or more of any character
# ^          Start of line
# $          End of line

# SEVERITY LEVELS:
#
# "critical" - Immediate security risk (passwords, keys, tokens)
# "warning"  - PII or sensitive data (emails, IDs, phone numbers)  
# "info"     - Internal structure info (paths, hostnames)
