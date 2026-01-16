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
        console.print(f"[dim]Using hybrid semantic + keyword search across {len(all_evidence)} evidence pieces...[/dim]")
        
        # Generate embedding for question
        question_embedding = self._get_embedding(question)
        if question_embedding is None:
            console.print("[yellow]Failed to generate question embedding, falling back to keyword search[/yellow]")
            return self._keyword_search(question, all_evidence, top_k)
        
        # Extract keywords for hybrid scoring
        keywords = self._extract_keywords(question)
        
        # Compute hybrid scores (semantic + keyword)
        scored_evidence = []
        for evidence in all_evidence:
            # Get or generate evidence embedding
            evidence_embedding = self._get_evidence_embedding(evidence)
            
            if evidence_embedding is not None:
                # Semantic similarity (cosine similarity)
                semantic_score = self._cosine_similarity(question_embedding, evidence_embedding)
                
                # Keyword matching score (normalized 0-1)
                evidence_text = f"{evidence.get('command', '')} {evidence.get('summary', '')}"
                keyword_score = self._keyword_score(evidence_text, keywords)
                # Normalize keyword score to 0-1 range (assume max 10 keyword matches)
                keyword_score_normalized = min(keyword_score / 10.0, 1.0)
                
                # Hybrid score: 70% semantic, 30% keyword (keyword helps with exact technical terms)
                hybrid_score = (0.7 * semantic_score) + (0.3 * keyword_score_normalized)
                
                scored_evidence.append((hybrid_score, semantic_score, keyword_score_normalized, evidence))
        
        # Sort by hybrid score
        scored_evidence.sort(reverse=True, key=lambda x: x[0])
        
        if scored_evidence:
            top = scored_evidence[0]
            console.print(f"[dim]Top match: {top[3]['command']} (hybrid: {top[0]:.2f}, semantic: {top[1]:.2f}, keyword: {top[2]:.2f})[/dim]")
        
        # Get top candidates for LLM reranking (retrieve more than needed for better reranking)
        top_candidates = [evidence for _, _, _, evidence in scored_evidence[:min(20, len(scored_evidence))]]
        
        # Use LLM reranking to get final top_k (better precision than pure similarity)
        if len(top_candidates) > top_k:
            console.print(f"[dim]LLM reranking top {len(top_candidates)} candidates to {top_k} most relevant...[/dim]")
            return self._llm_rerank(question, top_candidates, top_k)
        
        return top_candidates[:top_k]
    
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
        
        # Generate embedding for evidence summary with enriched context
        # Include command, investigation context, summary, and key findings for better semantic matching
        parts = []
        
        if evidence.get('command'):
            parts.append(f"Command: {evidence['command']}")
        
        if evidence.get('investigation_task'):
            parts.append(f"Context: {evidence['investigation_task']}")
        
        if evidence.get('summary'):
            parts.append(f"Summary: {evidence['summary']}")
        
        # Include top 5 key findings for richer semantic content
        key_findings = evidence.get('structured_data', {}).get('key_findings', [])
        if key_findings:
            findings_text = ', '.join([f['finding'] for f in key_findings[:5]])
            parts.append(f"Key Findings: {findings_text}")
        
        summary_text = '\n'.join(parts) if parts else evidence.get('command', '')
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
        # Build richer summaries for LLM reranking
        summaries = []
        for i, c in enumerate(candidates):
            cmd = c.get('command', 'N/A')
            summary = c.get('summary', 'No summary')[:150]
            # Include key finding if available for better context
            key_findings = c.get('structured_data', {}).get('key_findings', [])
            finding = f" | Key: {key_findings[0]['finding'][:100]}" if key_findings else ""
            summaries.append(f"{i}. [{cmd}] {summary}{finding}")
        
        summaries_text = "\n".join(summaries)
        
        prompt = f"""You are analyzing a Windows crash dump. The user asked: "{question}"

Rank these evidence pieces by relevance to answering the question. Consider:
- Does it directly answer the question?
- Does it provide supporting evidence?
- Is it technically relevant to the issue?

Evidence candidates:
{summaries_text}

Return the indices of the top {top_k} MOST relevant pieces in ORDER of relevance (most relevant first).
Return ONLY valid JSON: {{"indices": [3, 0, 7, ...]}}"""

        messages = [
            SystemMessage(content="You are an expert at identifying relevant technical evidence in crash dump analysis. Return only valid JSON."),
            HumanMessage(content=prompt)
        ]
        
        try:
            response = self.llm.invoke(messages)
            result = self._extract_json(response.content)
            if result and 'indices' in result:
                indices = result['indices'][:top_k]  # Ensure we don't exceed top_k
                # Validate indices and return valid candidates
                valid_candidates = [candidates[i] for i in indices if isinstance(i, int) and 0 <= i < len(candidates)]
                if valid_candidates:
                    return valid_candidates
        except Exception as e:
            console.print(f"[dim yellow]⚠ LLM reranking failed ({e}), using similarity order[/dim yellow]")
        
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
