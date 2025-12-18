"""Evidence storage with SQLite backend."""

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any


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
        metadata: dict = None
    ) -> str:
        """Store evidence with optional analysis results.
        
        Args:
            command: Debugger command executed
            output: Command output (will be saved to file if large)
            summary: Brief summary of findings
            key_findings: List of key findings
            embedding: Embedding vector for semantic search
            metadata: Additional metadata
            
        Returns:
            Evidence ID
        """
        evidence_id = self._generate_id(command)
        output_size = len(output)
        
        # Store output to file
        file_path = self.evidence_dir / f"{evidence_id}.txt"
        file_path.write_text(output, encoding='utf-8')
        
        # Store in database
        self.conn.execute("""
            INSERT INTO evidence (
                id, session_id, command, file_path, size,
                summary, key_findings, embedding, metadata, timestamp
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, [
            evidence_id,
            self.session_id,
            command,
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
    
    def find_by_command(self, command: str) -> str | None:
        """Find most recent evidence for a command (session-wide).
        
        For dump analysis where output is deterministic.
        
        Args:
            command: Command to find
            
        Returns:
            Evidence ID if found, None otherwise
        """
        cursor = self.conn.execute("""
            SELECT id FROM evidence 
            WHERE command = ?
            ORDER BY timestamp DESC
            LIMIT 1
        """, [command])
        
        row = cursor.fetchone()
        return row[0] if row else None
    
    def find_recent_duplicate(self, command: str, output: str, max_age_seconds: int = None) -> str | None:
        """Check if identical evidence exists in the session.
        
        For dump analysis, dumps are static so we cache for entire session lifetime.
        For live debugging, use max_age_seconds to limit cache duration.
        
        Args:
            command: Command to check
            output: Output to compare
            max_age_seconds: Maximum age in seconds (None = session lifetime for dumps)
            
        Returns:
            Evidence ID if duplicate found, None otherwise
        """
        import hashlib
        from datetime import datetime, timedelta
        
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
            """, [command])
        else:
            # Time-limited cache for live debugging
            cutoff_time = (datetime.now() - timedelta(seconds=max_age_seconds)).isoformat()
            cursor = self.conn.execute("""
                SELECT id, file_path, timestamp 
                FROM evidence 
                WHERE command = ? AND timestamp > ?
                ORDER BY timestamp DESC
            """, [command, cutoff_time])
        
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
        for chunk_num, chunk_text, analysis in chunks:
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
