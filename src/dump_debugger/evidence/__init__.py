"""Evidence management system for large debugger outputs."""

from dump_debugger.evidence.storage import EvidenceStore
from dump_debugger.evidence.analyzer import EvidenceAnalyzer
from dump_debugger.evidence.retrieval import EvidenceRetriever

__all__ = ['EvidenceStore', 'EvidenceAnalyzer', 'EvidenceRetriever']
