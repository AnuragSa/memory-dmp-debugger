import pytest
from unittest.mock import MagicMock

from dump_debugger.evidence.retrieval import EvidenceRetriever


def test_keyword_search_handles_none_summary():
    """Ensure evidence with missing summaries does not crash keyword search."""
    retriever = EvidenceRetriever(evidence_store=MagicMock(), llm=MagicMock(), embeddings_client=None)
    evidence_inventory = {
        "task1": [
            {"command": "!threads", "summary": None},
            {"command": "!clrstack", "summary": "Stack trace information"},
        ]
    }

    result = retriever.find_relevant_evidence(
        question="what is thread 6 doing", evidence_inventory=evidence_inventory, top_k=5, use_embeddings=False
    )

    # Should return only evidence with usable summaries and never raise
    assert all(e.get("summary") is not None for e in result)
