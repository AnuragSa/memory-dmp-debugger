"""Session management for isolating analyses."""

import json
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


class SessionManager:
    """Manages analysis sessions and storage."""
    
    def __init__(self, base_dir: Path = None):
        """Initialize session manager.
        
        Args:
            base_dir: Base directory for sessions (defaults to .sessions/)
        """
        if base_dir is None:
            base_dir = Path.cwd() / ".sessions"
        
        self.base_dir = base_dir
        self.base_dir.mkdir(exist_ok=True)
    
    def create_session(self, dump_path: Path) -> Path:
        """Create a new session directory.
        
        Args:
            dump_path: Path to dump file being analyzed
            
        Returns:
            Session directory path
        """
        session_id = self._generate_session_id(dump_path)
        session_dir = self.base_dir / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        
        # Store session metadata
        metadata = {
            'session_id': session_id,
            'dump_path': str(dump_path),
            'dump_name': dump_path.name,
            'created_at': datetime.now().isoformat(),
            'last_accessed': datetime.now().isoformat()
        }
        
        metadata_path = session_dir / "metadata.json"
        metadata_path.write_text(json.dumps(metadata, indent=2))
        
        return session_dir
    
    def _generate_session_id(self, dump_path: Path) -> str:
        """Generate unique session ID.
        
        Args:
            dump_path: Path to dump file
            
        Returns:
            Session ID
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dump_name = dump_path.stem.replace(' ', '_').replace('.', '_')
        # Limit dump name to reasonable length
        if len(dump_name) > 40:
            dump_name = dump_name[:40]
        return f"session_{timestamp}_{dump_name}"
    
    def update_access_time(self, session_dir: Path):
        """Update last access time for session.
        
        Args:
            session_dir: Session directory
        """
        metadata_path = session_dir / "metadata.json"
        if metadata_path.exists():
            try:
                metadata = json.loads(metadata_path.read_text())
                metadata['last_accessed'] = datetime.now().isoformat()
                metadata_path.write_text(json.dumps(metadata, indent=2))
            except:
                pass
    
    def list_sessions(self, limit: int = 20) -> list[dict]:
        """List all sessions with metadata.
        
        Args:
            limit: Maximum number of sessions to return
            
        Returns:
            List of session metadata dictionaries
        """
        sessions = []
        
        for session_dir in sorted(self.base_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
            if not session_dir.is_dir():
                continue
            
            metadata_path = session_dir / "metadata.json"
            if metadata_path.exists():
                try:
                    metadata = json.loads(metadata_path.read_text())
                    
                    # Add size info
                    total_size = sum(
                        f.stat().st_size 
                        for f in session_dir.rglob('*') 
                        if f.is_file()
                    )
                    metadata['size_mb'] = round(total_size / (1024 * 1024), 2)
                    metadata['session_dir'] = str(session_dir)
                    
                    # Count evidence
                    evidence_db = session_dir / "evidence.db"
                    evidence_count = 0
                    if evidence_db.exists():
                        try:
                            import sqlite3
                            conn = sqlite3.connect(str(evidence_db))
                            row = conn.execute("SELECT COUNT(*) FROM evidence").fetchone()
                            evidence_count = row[0] if row else 0
                            conn.close()
                        except:
                            pass
                    metadata['evidence_count'] = evidence_count
                    
                    sessions.append(metadata)
                    
                    if len(sessions) >= limit:
                        break
                except:
                    continue
        
        return sessions
    
    def cleanup_old_sessions(
        self,
        days_old: int = 7,
        keep_recent: int = 5
    ) -> list[str]:
        """Remove sessions older than specified days, keeping most recent ones.
        
        Args:
            days_old: Delete sessions older than this many days
            keep_recent: Always keep this many most recent sessions
            
        Returns:
            List of deleted session IDs
        """
        cutoff_time = datetime.now() - timedelta(days=days_old)
        deleted = []
        
        # Get all sessions sorted by creation time
        all_sessions = []
        for session_dir in self.base_dir.iterdir():
            if not session_dir.is_dir():
                continue
            
            metadata_path = session_dir / "metadata.json"
            if metadata_path.exists():
                try:
                    metadata = json.loads(metadata_path.read_text())
                    created = datetime.fromisoformat(metadata['created_at'])
                    all_sessions.append((created, session_dir, metadata['session_id']))
                except:
                    continue
        
        # Sort by creation time (newest first)
        all_sessions.sort(reverse=True, key=lambda x: x[0])
        
        # Delete old sessions, but keep most recent ones
        for i, (created, session_dir, session_id) in enumerate(all_sessions):
            # Always keep the most recent sessions
            if i < keep_recent:
                continue
            
            # Delete if older than cutoff
            if created < cutoff_time:
                try:
                    shutil.rmtree(session_dir)
                    deleted.append(session_id)
                except Exception as e:
                    print(f"Warning: Failed to delete {session_id}: {e}")
        
        return deleted
    
    def get_session_info(self, session_dir: Path) -> dict:
        """Get detailed info about a session.
        
        Args:
            session_dir: Session directory
            
        Returns:
            Session information dictionary
        """
        metadata_path = session_dir / "metadata.json"
        if not metadata_path.exists():
            return {'error': 'Session metadata not found'}
        
        try:
            metadata = json.loads(metadata_path.read_text())
            
            # Count evidence
            evidence_db = session_dir / "evidence.db"
            evidence_count = 0
            if evidence_db.exists():
                import sqlite3
                conn = sqlite3.connect(str(evidence_db))
                row = conn.execute("SELECT COUNT(*) FROM evidence").fetchone()
                evidence_count = row[0] if row else 0
                conn.close()
            
            # Size
            total_size = sum(
                f.stat().st_size 
                for f in session_dir.rglob('*') 
                if f.is_file()
            )
            
            metadata['evidence_count'] = evidence_count
            metadata['size_mb'] = round(total_size / (1024 * 1024), 2)
            metadata['session_dir'] = str(session_dir)
            
            return metadata
        except Exception as e:
            return {'error': str(e)}
