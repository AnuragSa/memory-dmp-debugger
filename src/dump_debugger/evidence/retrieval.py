"""Evidence retrieval with semantic search using embeddings."""

import json
import numpy as np
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from rich.console import Console

console = Console()


class EvidenceRetriever:
    """Retrieve relevant evidence using semantic search with embeddings."""
    
    def __init__(self, evidence_store, llm, embeddings_client=None):
        """Initialize retriever.
        
        Args:
            evidence_store: EvidenceStore instance
            llm: LLM instance for reranking
            embeddings_client: OpenAI client for embeddings (optional)
        """
        self.evidence_store = evidence_store
        self.llm = llm
        self.embeddings_client = embeddings_client
    
    def find_relevant_evidence(
        self,
        question: str,
        evidence_inventory: dict,
        top_k: int = 10,
        use_embeddings: bool = True
    ) -> list[dict]:
        """Find most relevant evidence for a question.
        
        Args:
            question: User's question
            evidence_inventory: Evidence from state
            top_k: Number of results to return
            use_embeddings: Whether to use semantic search with embeddings
            
        Returns:
            List of relevant evidence pieces
        """
        all_evidence = self._flatten_evidence(evidence_inventory)
        
        if not all_evidence:
            return []
        
        # Use embeddings if available and requested
        if use_embeddings and self.embeddings_client:
            return self._semantic_search(question, all_evidence, top_k)
        else:
            return self._keyword_search(question, all_evidence, top_k)
    
    def _flatten_evidence(self, evidence_inventory: dict) -> list[dict]:
        """Flatten evidence inventory into a list.
        
        Args:
            evidence_inventory: Nested evidence dictionary
            
        Returns:
            Flat list of evidence pieces
        """
        all_evidence = []
        for task, evidence_list in evidence_inventory.items():
            for evidence in evidence_list:
                evidence['investigation_task'] = task
                all_evidence.append(evidence)
        return all_evidence
    
    def _semantic_search(
        self,
        question: str,
        all_evidence: list[dict],
        top_k: int
    ) -> list[dict]:
        """Semantic search using embeddings.
        
        Args:
            question: User's question
            all_evidence: All evidence pieces
            top_k: Number of results
            
        Returns:
            Top K most relevant evidence pieces
        """
        console.print(f"[dim]Using semantic search across {len(all_evidence)} evidence pieces...[/dim]")
        
        # Generate embedding for question
        question_embedding = self._get_embedding(question)
        if question_embedding is None:
            console.print("[yellow]Failed to generate question embedding, falling back to keyword search[/yellow]")
            return self._keyword_search(question, all_evidence, top_k)
        
        # Compute similarities
        similarities = []
        for evidence in all_evidence:
            # Get or generate evidence embedding
            evidence_embedding = self._get_evidence_embedding(evidence)
            
            if evidence_embedding is not None:
                # Cosine similarity
                similarity = self._cosine_similarity(question_embedding, evidence_embedding)
                similarities.append((similarity, evidence))
        
        # Sort by similarity and return top K
        similarities.sort(reverse=True, key=lambda x: x[0])
        
        if similarities:
            console.print(f"[dim]Top match: {similarities[0][1]['command']} (score: {similarities[0][0]:.2f})[/dim]")
        
        return [evidence for _, evidence in similarities[:top_k]]
    
    def _keyword_search(
        self,
        question: str,
        all_evidence: list[dict],
        top_k: int
    ) -> list[dict]:
        """Keyword-based search with LLM reranking.
        
        Args:
            question: User's question
            all_evidence: All evidence pieces
            top_k: Number of results
            
        Returns:
            Top K most relevant evidence pieces
        """
        console.print(f"[dim]Using keyword search across {len(all_evidence)} evidence pieces...[/dim]")
        
        # Extract keywords
        keywords = self._extract_keywords(question)
        
        # Score by keyword matching
        scored = []
        for evidence in all_evidence:
            score = self._keyword_score(evidence.get('summary', ''), keywords)
            if score > 0:
                scored.append((score, evidence))
        
        # Sort and take top candidates
        scored.sort(reverse=True, key=lambda x: x[0])
        candidates = [e for _, e in scored[:min(20, len(scored))]]
        
        # LLM rerank if we have many candidates
        if len(candidates) > top_k:
            candidates = self._llm_rerank(question, candidates, top_k)
        
        return candidates[:top_k]
    
    def _get_embedding(self, text: str) -> list[float] | None:
        """Generate embedding for text.
        
        Args:
            text: Text to embed
            
        Returns:
            Embedding vector or None if failed
        """
        if not self.embeddings_client:
            return None
        
        try:
            from dump_debugger.config import settings
            
            # Get model/deployment name
            if settings.embeddings_provider == "azure" and settings.azure_embeddings_deployment:
                # Azure OpenAI uses deployment name instead of model
                response = self.embeddings_client.embeddings.create(
                    model=settings.azure_embeddings_deployment,
                    input=text
                )
            else:
                # Standard OpenAI
                response = self.embeddings_client.embeddings.create(
                    model=settings.embeddings_model,
                    input=text
                )
            return response.data[0].embedding
        except Exception as e:
            console.print(f"[yellow]Embedding generation failed: {e}[/yellow]")
            return None
    
    def _get_evidence_embedding(self, evidence: dict) -> list[float] | None:
        """Get or generate embedding for evidence.
        
        Args:
            evidence: Evidence dictionary
            
        Returns:
            Embedding vector or None
        """
        # Check if evidence has stored embedding (external evidence)
        if evidence.get('evidence_type') == 'external':
            evidence_id = evidence.get('evidence_id')
            if evidence_id:
                try:
                    metadata = self.evidence_store.get_metadata(evidence_id)
                    # Embedding is stored in database
                    all_evidence = self.evidence_store.get_all_evidence()
                    for ev in all_evidence:
                        if ev['evidence_id'] == evidence_id and ev['embedding']:
                            return ev['embedding']
                except:
                    pass
        
        # Generate embedding for evidence summary
        summary_text = f"{evidence.get('command', '')}: {evidence.get('summary', '')}"
        return self._get_embedding(summary_text)
    
    def _cosine_similarity(self, vec1: list[float], vec2: list[float]) -> float:
        """Compute cosine similarity between two vectors.
        
        Args:
            vec1: First vector
            vec2: Second vector
            
        Returns:
            Similarity score (0-1)
        """
        v1 = np.array(vec1)
        v2 = np.array(vec2)
        
        dot_product = np.dot(v1, v2)
        norm1 = np.linalg.norm(v1)
        norm2 = np.linalg.norm(v2)
        
        if norm1 == 0 or norm2 == 0:
            return 0.0
        
        return float(dot_product / (norm1 * norm2))
    
    def _extract_keywords(self, question: str) -> list[str]:
        """Extract keywords from question.
        
        Args:
            question: User's question
            
        Returns:
            List of keywords
        """
        # Simple keyword extraction - split and filter
        words = question.lower().split()
        stopwords = {'the', 'is', 'are', 'was', 'were', 'what', 'when', 'where', 'how', 'why', 'can', 'you', 'show', 'me', 'a', 'an'}
        keywords = [w for w in words if len(w) > 3 and w not in stopwords]
        return keywords
    
    def _keyword_score(self, text: str | None, keywords: list[str]) -> int:
        """Score text by keyword matches.
        
        Args:
            text: Text to score
            keywords: Keywords to match
            
        Returns:
            Match score
        """
        if not text:
            return 0
        text_lower = str(text).lower()
        score = 0
        for keyword in keywords:
            if keyword in text_lower:
                score += text_lower.count(keyword)
        return score
    
    def _llm_rerank(
        self,
        question: str,
        candidates: list[dict],
        top_k: int
    ) -> list[dict]:
        """Use LLM to rerank candidates by relevance.
        
        Args:
            question: User's question
            candidates: Candidate evidence pieces
            top_k: Number to return
            
        Returns:
            Reranked evidence pieces
        """
        summaries = "\n".join([
            f"{i}. [{c.get('command', 'N/A')}] {c.get('summary', 'No summary')[:150]}"
            for i, c in enumerate(candidates)
        ])
        
        prompt = f"""Question: {question}

Evidence candidates:
{summaries}

Return the indices of the {top_k} MOST relevant pieces in order of relevance.
JSON: {{"indices": [3, 0, 7, ...]}}"""

        messages = [
            SystemMessage(content="You are an expert at identifying relevant technical evidence."),
            HumanMessage(content=prompt)
        ]
        
        try:
            response = self.llm.invoke(messages)
            result = self._extract_json(response.content)
            if result and 'indices' in result:
                indices = result['indices']
                return [candidates[i] for i in indices if i < len(candidates)]
        except:
            pass
        
        # Fallback: return candidates as-is
        return candidates[:top_k]
    
    def _extract_json(self, text: str) -> dict | None:
        """Extract JSON from text."""
        try:
            return json.loads(text)
        except:
            pass
        
        # Find JSON block
        start = text.find('{')
        end = text.rfind('}')
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end+1])
            except:
                pass
        
        return None
