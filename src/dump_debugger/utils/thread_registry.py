"""Thread registry for mapping between different thread ID formats.

Thread ID types in WinDbg/.NET debugging:
1. DBG# (dbg_id): Debugger thread index (0, 1, 2...) - used in ~<n>e commands
2. Managed ID (managed_id): CLR's internal thread ID (1, 2, 12, 19...) - most user-friendly
3. OSID: Operating system thread ID in hex (d78, 3fc...) - used in ~~[osid]e commands

The managed ID is the most comprehensible for users as it matches what they see
in Visual Studio and other managed debuggers.
"""

from dataclasses import dataclass
from typing import Dict, Optional


@dataclass
class ThreadInfo:
    """Information about a single thread."""
    dbg_id: int  # Debugger thread index (0, 1, 2...)
    managed_id: int  # CLR managed thread ID (1, 2, 12...)
    osid: str  # OS thread ID in hex (without 0x prefix)
    thread_obj: Optional[str] = None  # Thread object address
    apartment: Optional[str] = None  # MTA, STA, etc.
    special: Optional[str] = None  # Finalizer, GC, etc.


class ThreadRegistry:
    """Global registry for thread ID mappings.
    
    Populated when !threads is analyzed, used to display user-friendly
    managed IDs when referencing threads from other commands like !clrstack.
    """
    
    _instance: Optional['ThreadRegistry'] = None
    
    def __new__(cls):
        """Singleton pattern to ensure one registry per process."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._threads = {}  # OSID → ThreadInfo
            cls._instance._by_dbg_id = {}  # DBG# → ThreadInfo
            cls._instance._by_managed_id = {}  # Managed ID → ThreadInfo
        return cls._instance
    
    def clear(self):
        """Clear all thread mappings (for new session)."""
        self._threads.clear()
        self._by_dbg_id.clear()
        self._by_managed_id.clear()
    
    def register_thread(
        self,
        dbg_id: int,
        managed_id: int,
        osid: str,
        thread_obj: Optional[str] = None,
        apartment: Optional[str] = None,
        special: Optional[str] = None,
    ):
        """Register a thread with all its ID mappings.
        
        Args:
            dbg_id: Debugger thread index (0, 1, 2...)
            managed_id: CLR managed thread ID
            osid: OS thread ID in hex (without 0x prefix)
            thread_obj: Thread object address
            apartment: Apartment type (MTA, STA)
            special: Special designation (Finalizer, GC, etc.)
        """
        # Normalize OSID to lowercase without 0x prefix
        osid_normalized = osid.lower().lstrip('0x')
        
        info = ThreadInfo(
            dbg_id=dbg_id,
            managed_id=managed_id,
            osid=osid_normalized,
            thread_obj=thread_obj,
            apartment=apartment,
            special=special,
        )
        
        self._threads[osid_normalized] = info
        self._by_dbg_id[dbg_id] = info
        self._by_managed_id[managed_id] = info
    
    def get_by_osid(self, osid: str) -> Optional[ThreadInfo]:
        """Lookup thread by OS thread ID.
        
        Args:
            osid: OS thread ID in hex (with or without 0x prefix)
            
        Returns:
            ThreadInfo if found, None otherwise
        """
        osid_normalized = osid.lower().lstrip('0x')
        return self._threads.get(osid_normalized)
    
    def get_by_dbg_id(self, dbg_id: int) -> Optional[ThreadInfo]:
        """Lookup thread by debugger thread index.
        
        Args:
            dbg_id: Debugger thread index
            
        Returns:
            ThreadInfo if found, None otherwise
        """
        return self._by_dbg_id.get(dbg_id)
    
    def get_by_managed_id(self, managed_id: int) -> Optional[ThreadInfo]:
        """Lookup thread by managed thread ID.
        
        Args:
            managed_id: CLR managed thread ID
            
        Returns:
            ThreadInfo if found, None otherwise
        """
        return self._by_managed_id.get(managed_id)
    
    def format_thread_id(self, osid: str, include_details: bool = False) -> str:
        """Format a thread identifier for user display.
        
        Prefers managed ID as it's most user-friendly.
        Falls back to OSID if thread not in registry.
        
        Args:
            osid: OS thread ID in hex
            include_details: Whether to include extra info (apartment, special)
            
        Returns:
            Formatted string like "Thread 12" or "Thread 12 (Finalizer)"
        """
        info = self.get_by_osid(osid)
        
        if info:
            base = f"Thread {info.managed_id}"
            if include_details and info.special:
                base += f" ({info.special})"
            return base
        else:
            # Fallback to OSID if not registered
            return f"Thread (OSID 0x{osid})"
    
    def format_thread_id_from_dbg(self, dbg_id: int, include_details: bool = False) -> str:
        """Format a thread identifier from DBG# for user display.
        
        Args:
            dbg_id: Debugger thread index
            include_details: Whether to include extra info
            
        Returns:
            Formatted string like "Thread 12" or "Thread 12 (MTA)"
        """
        info = self.get_by_dbg_id(dbg_id)
        
        if info:
            base = f"Thread {info.managed_id}"
            if include_details and info.special:
                base += f" ({info.special})"
            return base
        else:
            # Fallback to DBG# if not registered
            return f"Thread ~{dbg_id}"
    
    @property
    def thread_count(self) -> int:
        """Number of registered threads."""
        return len(self._threads)
    
    def is_populated(self) -> bool:
        """Check if registry has any threads registered."""
        return len(self._threads) > 0


# Global singleton instance
thread_registry = ThreadRegistry()


def get_thread_registry() -> ThreadRegistry:
    """Get the global thread registry instance."""
    return thread_registry
