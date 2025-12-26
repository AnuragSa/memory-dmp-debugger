"""Command analyzers for specialized debugger output analysis."""

from dump_debugger.analyzers.base import BaseAnalyzer, AnalysisResult
from dump_debugger.analyzers.registry import analyzer_registry, get_analyzer
from dump_debugger.analyzers.threads import ThreadsAnalyzer
from dump_debugger.analyzers.dumpheap import DumpHeapAnalyzer
from dump_debugger.analyzers.clrstack import CLRStackAnalyzer
from dump_debugger.analyzers.syncblk import SyncBlockAnalyzer
from dump_debugger.analyzers.threadpool import ThreadPoolAnalyzer
from dump_debugger.analyzers.finalizequeue import FinalizeQueueAnalyzer
from dump_debugger.analyzers.gchandles import GCHandlesAnalyzer
from dump_debugger.analyzers.eeheap import EEHeapAnalyzer
from dump_debugger.analyzers.gcroot import GCRootAnalyzer
from dump_debugger.analyzers.do import DOAnalyzer
from dump_debugger.analyzers.dso import DSOAnalyzer
from dump_debugger.analyzers.handle import HandleAnalyzer

# Register analyzers on module import (sorted by tier for optimal routing)
analyzer_registry.register(ThreadsAnalyzer)
analyzer_registry.register(SyncBlockAnalyzer)
analyzer_registry.register(ThreadPoolAnalyzer)
analyzer_registry.register(FinalizeQueueAnalyzer)
analyzer_registry.register(EEHeapAnalyzer)
analyzer_registry.register(DOAnalyzer)
analyzer_registry.register(DSOAnalyzer)
analyzer_registry.register(HandleAnalyzer)
analyzer_registry.register(DumpHeapAnalyzer)
analyzer_registry.register(GCHandlesAnalyzer)
analyzer_registry.register(GCRootAnalyzer)
analyzer_registry.register(CLRStackAnalyzer)

__all__ = [
    "BaseAnalyzer",
    "AnalysisResult",
    "analyzer_registry",
    "get_analyzer",
    "ThreadsAnalyzer",
    "DumpHeapAnalyzer",
    "CLRStackAnalyzer",
    "SyncBlockAnalyzer",
    "ThreadPoolAnalyzer",
    "FinalizeQueueAnalyzer",
    "GCHandlesAnalyzer",
    "EEHeapAnalyzer",
    "GCRootAnalyzer",
    "DOAnalyzer",
    "DSOAnalyzer",
    "HandleAnalyzer",
]
