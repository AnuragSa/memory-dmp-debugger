"""Evidence storage with SQLite backend."""

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from rich.console import Console

console = Console()


class EvidenceStore:
    """External storage for large debugger outputs with embeddings."""
    
    def __init__(self, session_dir: Path):
        """Initialize evidence store for a session.
        
        Args:
            session_dir: Session directory for this analysis
        """
        self.session_dir = session_dir
        self.evidence_dir = session_dir / "evidence"
        self.evidence_dir.mkdir(exist_ok=True, parents=True)
        
        self.db_path = session_dir / "evidence.db"
        self.conn = sqlite3.connect(str(self.db_path))
        self.session_id = session_dir.name
        self._init_db()
    
    def _init_db(self):
        """Initialize SQLite schema."""
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS evidence (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                command TEXT NOT NULL,
                file_path TEXT,
                size INTEGER,
                summary TEXT,
                key_findings TEXT,
                embedding TEXT,
                metadata TEXT,
                timestamp TEXT NOT NULL
            )
        """)
        
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                evidence_id TEXT NOT NULL,
                chunk_num INTEGER NOT NULL,
                chunk_text TEXT NOT NULL,
                analysis TEXT,
                FOREIGN KEY (evidence_id) REFERENCES evidence(id)
            )
        """)
        
        self.conn.commit()
    
    def _generate_id(self, command: str) -> str:
        """Generate unique evidence ID."""
        import re
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        # Sanitize command for use in filename - remove invalid Windows filename characters
        # Invalid chars: < > : " / \ | ? * and control characters
        cmd_prefix = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', command)
        cmd_prefix = cmd_prefix.replace(' ', '_').replace('!', '').replace('~', '')[:20]
        return f"ev_{cmd_prefix}_{timestamp}"
    
    def store_evidence(
        self,
        command: str,
        output: str,
        summary: str = None,
        key_findings: list[str] = None,
        embedding: list[float] = None,
        metadata: dict = None,
        current_thread: str = None
    ) -> str:
        """Store evidence with optional analysis results.
        
        Args:
            command: Debugger command executed
            output: Command output (will be saved to file if large)
            summary: Brief summary of findings
            key_findings: List of key findings
            embedding: Embedding vector for semantic search
            metadata: Additional metadata
            current_thread: Current debugger thread (e.g., "12" or "0x25b8") for thread-sensitive commands
            
        Returns:
            Evidence ID
        """
        evidence_id = self._generate_id(command)
        output_size = len(output)
        
        # Thread-sensitive commands should include thread context in cache key
        thread_sensitive_commands = [
            '!clrstack', '!dso', 'k', 'kb', 'kn', 'kp', 'kv',
            '!do', '!dumpobj', 'r', 'dt', 'dv', '!tls'
        ]
        
        # Build cache key with thread context for thread-sensitive commands
        cache_command = command
        if current_thread:
            cmd_lower = command.lower().strip()
            # Check if command is thread-sensitive
            if any(cmd_lower.startswith(sensitive_cmd.lower()) for sensitive_cmd in thread_sensitive_commands):
                cache_command = f"{command}@thread_{current_thread}"
        
        # Store output to file
        file_path = self.evidence_dir / f"{evidence_id}.txt"
        file_path.write_text(output, encoding='utf-8')
        
        # Store in database with cache_command (includes thread context for thread-sensitive commands)
        self.conn.execute("""
            INSERT INTO evidence (
                id, session_id, command, file_path, size,
                summary, key_findings, embedding, metadata, timestamp
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, [
            evidence_id,
            self.session_id,
            cache_command,  # Store with thread context for proper cache lookups
            str(file_path),
            output_size,
            summary or '',
            json.dumps(key_findings or []),
            json.dumps(embedding) if embedding else None,
            json.dumps(metadata or {}),
            datetime.now().isoformat()
        ])
        self.conn.commit()
        
        return evidence_id
    
    def find_by_command(self, command: str, current_thread: str = None) -> str | None:
        """Find most recent evidence for a command (session-wide).
        
        For dump analysis where output is deterministic.
        Thread-sensitive commands include thread context in lookup to prevent
        returning cached results from different threads.
        
        Args:
            command: Command to find
            current_thread: Current thread context (e.g., "12" or "0x25b8") for thread-sensitive commands
            
        Returns:
            Evidence ID if found, None otherwise
        """
        # Thread-sensitive commands should include thread context in cache key
        thread_sensitive_commands = [
            '!clrstack', '!dso', 'k', 'kb', 'kn', 'kp', 'kv',
            '!do', '!dumpobj', 'r', 'dt', 'dv', '!tls'
        ]
        
        # Build cache key with thread context for thread-sensitive commands
        cache_command = command
        if current_thread:
            cmd_lower = command.lower().strip()
            # Check if command is thread-sensitive
            if any(cmd_lower.startswith(sensitive_cmd.lower()) for sensitive_cmd in thread_sensitive_commands):
                cache_command = f"{command}@thread_{current_thread}"
        
        cursor = self.conn.execute("""
            SELECT id FROM evidence 
            WHERE command = ?
            ORDER BY timestamp DESC
            LIMIT 1
        """, [cache_command])
        
        row = cursor.fetchone()
        return row[0] if row else None
    
    def find_recent_duplicate(self, command: str, output: str, max_age_seconds: int = None, current_thread: str = None) -> str | None:
        """Check if identical evidence exists in the session.
        
        For dump analysis, dumps are static so we cache for entire session lifetime.
        For live debugging, use max_age_seconds to limit cache duration.
        
        Thread-context-sensitive commands include thread info in cache key to prevent
        returning cached results from different threads.
        
        Args:
            command: Command to check
            output: Output to compare
            max_age_seconds: Maximum age in seconds (None = session lifetime for dumps)
            current_thread: Current thread context (e.g., "12" or "0x1234")
            
        Returns:
            Evidence ID if duplicate found, None otherwise
        """
        import hashlib
        from datetime import datetime, timedelta
        
        # Thread-context-sensitive commands need thread info in cache key
        thread_sensitive_commands = [
            '!clrstack', '!dso', '!dumpstack', 'k', 'kb', 'kv', 'kp', 
            '!eestack', 'dv', '!do', '!dumpobj', '!dumpstack'
        ]
        
        # Check if command is thread-sensitive
        is_thread_sensitive = any(
            command.strip().lower().startswith(pattern.lower()) 
            for pattern in thread_sensitive_commands
        )
        
        # Build cache key: command + optional thread context
        if is_thread_sensitive and current_thread:
            # Include thread in cache key for thread-sensitive commands
            cache_command = f"{command}@thread_{current_thread}"
        else:
            cache_command = command
        
        # Calculate hash of current output
        output_hash = hashlib.sha256(output.encode('utf-8')).hexdigest()
        
        # Build query - no time limit for dump analysis (dumps are immutable)
        if max_age_seconds is None:
            # Session-wide cache - dumps don't change
            cursor = self.conn.execute("""
                SELECT id, file_path, timestamp 
                FROM evidence 
                WHERE command = ?
                ORDER BY timestamp DESC
            """, [cache_command])
        else:
            # Time-limited cache for live debugging
            cutoff_time = (datetime.now() - timedelta(seconds=max_age_seconds)).isoformat()
            cursor = self.conn.execute("""
                SELECT id, file_path, timestamp 
                FROM evidence 
                WHERE command = ? AND timestamp > ?
                ORDER BY timestamp DESC
            """, [cache_command, cutoff_time])
        
        for row in cursor:
            evidence_id, file_path, timestamp = row
            
            # Read existing output and compare hash
            try:
                existing_output = Path(file_path).read_text(encoding='utf-8')
                existing_hash = hashlib.sha256(existing_output.encode('utf-8')).hexdigest()
                
                if existing_hash == output_hash:
                    # Found identical evidence
                    return evidence_id
            except Exception:
                continue
        
        return None
    
    def store_chunks(self, evidence_id: str, chunks: list[tuple[int, str, dict]]):
        """Store analyzed chunks for an evidence piece.
        
        Args:
            evidence_id: Parent evidence ID
            chunks: List of (chunk_num, chunk_text, analysis_dict) tuples
        """
        # SQLite has INT_MAX limit (~2GB) for strings
        # Calculate total size and warn if too large
        MAX_CHUNK_SIZE = 100 * 1024 * 1024  # 100MB per chunk
        MAX_TOTAL_SIZE = 1024 * 1024 * 1024  # 1GB total (safe margin under 2GB limit)
        
        total_size = sum(len(chunk_text) for _, chunk_text, _ in chunks)
        
        if total_size > MAX_TOTAL_SIZE:
            console.print(f"[yellow]⚠ Chunks total {total_size:,} bytes (>{MAX_TOTAL_SIZE:,}), skipping chunk storage[/yellow]")
            console.print(f"[dim]  This prevents SQLite overflow errors. Analysis summary is still available.[/dim]")
            return
        
        for chunk_num, chunk_text, analysis in chunks:
            # Validate individual chunk size
            chunk_size = len(chunk_text)
            if chunk_size > MAX_CHUNK_SIZE:
                console.print(f"[yellow]⚠ Chunk {chunk_num} is {chunk_size:,} bytes (>{MAX_CHUNK_SIZE:,}), truncating[/yellow]")
                chunk_text = chunk_text[:MAX_CHUNK_SIZE] + "\n... [TRUNCATED]"
            
            self.conn.execute("""
                INSERT INTO chunks (evidence_id, chunk_num, chunk_text, analysis)
                VALUES (?, ?, ?, ?)
            """, [
                evidence_id,
                chunk_num,
                chunk_text,
                json.dumps(analysis)
            ])
        self.conn.commit()
    
    def update_embedding(self, evidence_id: str, embedding: list[float]):
        """Update embedding for evidence piece.
        
        Args:
            evidence_id: Evidence ID
            embedding: Embedding vector
        """
        self.conn.execute("""
            UPDATE evidence SET embedding = ? WHERE id = ?
        """, [json.dumps(embedding), evidence_id])
        self.conn.commit()
    
    def retrieve_evidence(self, evidence_id: str) -> str:
        """Retrieve full output by ID.
        
        Args:
            evidence_id: Evidence ID
            
        Returns:
            Full command output
        """
        row = self.conn.execute("""
            SELECT file_path FROM evidence WHERE id = ?
        """, [evidence_id]).fetchone()
        
        if not row:
            raise ValueError(f"Evidence {evidence_id} not found")
        
        return Path(row[0]).read_text(encoding='utf-8')
    
    def get_metadata(self, evidence_id: str) -> dict:
        """Get metadata for evidence without loading full content.
        
        Args:
            evidence_id: Evidence ID
            
        Returns:
            Metadata dictionary
        """
        row = self.conn.execute("""
            SELECT command, size, summary, key_findings, metadata, timestamp
            FROM evidence WHERE id = ?
        """, [evidence_id]).fetchone()
        
        if not row:
            raise ValueError(f"Evidence {evidence_id} not found")
        
        return {
            'command': row[0],
            'size': row[1],
            'summary': row[2],
            'key_findings': json.loads(row[3]) if row[3] else [],
            'metadata': json.loads(row[4]) if row[4] else {},
            'timestamp': row[5]
        }
    
    def get_all_evidence(self) -> list[dict]:
        """Get all evidence metadata for this session.
        
        Returns:
            List of evidence metadata dictionaries
        """
        rows = self.conn.execute("""
            SELECT id, command, size, summary, key_findings, embedding, timestamp
            FROM evidence
            ORDER BY timestamp
        """).fetchall()
        
        return [{
            'evidence_id': row[0],
            'command': row[1],
            'size': row[2],
            'summary': row[3],
            'key_findings': json.loads(row[4]) if row[4] else [],
            'embedding': json.loads(row[5]) if row[5] else None,
            'timestamp': row[6]
        } for row in rows]
    
    def close(self):
        """Close database connection."""
        if self.conn:
            self.conn.close()
    
    def __del__(self):
        """Cleanup on destruction."""
        self.close()
