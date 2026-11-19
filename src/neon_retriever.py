"""
Neon PostgreSQL & pgvector Retriever module for Groww Mutual Fund FAQ Assistant.
Provides semantic vector search over full precision vector(3072) with halfvec(3072)
HNSW indexing, scheme filtering, recency-boosted composite scoring, and resilient
keyword/BM25 fallback for quota exhaustion or offline reliability.
"""

from typing import List, Dict, Any, Optional
import logging
import re
import psycopg
from pgvector.psycopg import register_vector
from src.config import config
from src.llm import GeminiClient
from src.retriever import detect_scheme_from_query

logger = logging.getLogger(__name__)


class NeonRetriever:
    """Vector database retrieval engine backed by Neon PostgreSQL and pgvector."""

    def __init__(
        self,
        db_url: Optional[str] = None,
        llm_client: Optional[GeminiClient] = None,
    ):
        self.db_url = db_url or config.DATABASE_URL
        self.llm = llm_client or GeminiClient()

    def _get_connection(self) -> psycopg.Connection:
        """Establish connection to Neon PostgreSQL and register vector type."""
        conn = psycopg.connect(self.db_url)
        register_vector(conn)
        return conn

    def is_indexed(self) -> bool:
        """Check if the documents table in Neon has been migrated and contains records."""
        if not self.db_url:
            return False
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT to_regclass('public.documents');")
                    exists = cur.fetchone()[0]
                    if not exists:
                        return False
                    cur.execute("SELECT COUNT(*) FROM documents;")
                    count = cur.fetchone()[0]
                    return count > 0
        except Exception as e:
            logger.warning(f"Failed to check Neon index status: {e}")
            return False

    def retrieve(
        self,
        query: str,
        n_results: int = 5,
        scheme_filter: Optional[str] = None,
        relevance_threshold: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        """
        Semantic vector retrieval using Neon PostgreSQL and pgvector halfvec(3072) cosine search.
        Integrates scheme filtering, published date recency boost, and automatic keyword fallback.
        """
        top_k = min(max(1, n_results), 5)
        candidate_k = min(max(15, top_k * 3), 25)

        active_scheme_filter = scheme_filter or detect_scheme_from_query(query)

        # 1. Generate query embedding with fallback on API rate limit / quota exhaustion
        try:
            query_vector = self.llm.embed_text(query)
        except Exception as e:
            logger.warning(
                f"Embedding API unavailable ({e}). Falling back to Neon full-text keyword retrieval."
            )
            return self._fallback_keyword_retrieve(query, active_scheme_filter, top_k)

        # 2. Execute pgvector cosine distance search
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    query_params = {
                        "vec": query_vector,
                        "limit": candidate_k,
                    }
                    if active_scheme_filter:
                        where_sql = "WHERE scheme_name = %(scheme)s"
                        query_params["scheme"] = active_scheme_filter
                    else:
                        where_sql = ""

                    sql = f"""
                        SELECT 
                            chunk_id,
                            content,
                            scheme_name,
                            document_type,
                            document_title,
                            source_id,
                            source_url,
                            published_date,
                            accessed_date,
                            page_number,
                            metadata,
                            (embedding::halfvec(3072) <=> %(vec)s::halfvec(3072)) AS distance
                        FROM documents
                        {where_sql}
                        ORDER BY embedding::halfvec(3072) <=> %(vec)s::halfvec(3072) ASC
                        LIMIT %(limit)s;
                    """
                    cur.execute(sql, query_params)
                    rows = cur.fetchall()

            if not rows:
                return []

            retrieved = []
            for r in rows:
                dist = float(r[11]) if r[11] is not None else 1.0

                if relevance_threshold is not None and dist > relevance_threshold:
                    continue

                sim = max(0.0, 1.0 - dist)
                pub_date = str(r[7] or "")
                doc_title = str(r[4] or "")

                # Recency boost for latest applicable monthly disclosures
                recency_boost = 0.0
                if "2026" in pub_date:
                    recency_boost += 0.12
                    if "Factsheet" in doc_title:
                        recency_boost += 0.08
                elif "2025" in pub_date:
                    recency_boost += 0.02

                rel_score = sim + recency_boost

                retrieved.append({
                    "chunk_id": r[0],
                    "text": r[1],
                    "scheme_name": r[2],
                    "document_type": r[3],
                    "document_title": r[4],
                    "source_id": r[5],
                    "source_url": r[6],
                    "published_date": r[7] or "Date not available",
                    "accessed_date": r[8] or "Date not available",
                    "page_number": int(r[9]),
                    "metadata": r[10] if isinstance(r[10], dict) else {},
                    "distance": dist,
                    "relevance_score": rel_score,
                })

            retrieved.sort(key=lambda x: x["relevance_score"], reverse=True)
            return retrieved[:top_k]

        except Exception as e:
            logger.error(f"Error executing vector query on Neon: {e}", exc_info=True)
            return self._fallback_keyword_retrieve(query, active_scheme_filter, top_k)

    def _fallback_keyword_retrieve(
        self,
        query: str,
        scheme_filter: Optional[str] = None,
        top_k: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        Resilient keyword retrieval fallback on Neon using full-text search and term frequency.
        Ensures continuous service availability when embedding APIs are exhausted or unavailable.
        """
        stopwords = {
            "about", "after", "again", "all", "also", "and", "any", "are", "been", "both", "but",
            "can", "each", "few", "for", "from", "had", "has", "have", "how", "into", "its",
            "more", "most", "not", "our", "out", "she", "some", "such", "than", "that", "the",
            "their", "them", "then", "there", "these", "they", "this", "those", "was", "were",
            "what", "when", "where", "which", "who", "will", "with", "would", "you", "your"
        }
        words = set(re.findall(r"\b[a-zA-Z0-9.%]{3,}\b", query.lower())) - stopwords

        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    query_params = {}
                    if scheme_filter:
                        where_sql = "WHERE scheme_name = %(scheme)s"
                        query_params["scheme"] = scheme_filter
                    else:
                        where_sql = ""

                    sql = f"""
                        SELECT 
                            chunk_id,
                            content,
                            scheme_name,
                            document_type,
                            document_title,
                            source_id,
                            source_url,
                            published_date,
                            accessed_date,
                            page_number,
                            metadata
                        FROM documents
                        {where_sql};
                    """
                    cur.execute(sql, query_params)
                    rows = cur.fetchall()

            if not rows:
                return []

            scored = []
            for r in rows:
                content_lower = (r[1] or "").lower()
                doc_words = set(re.findall(r"\b[a-zA-Z0-9.%]{3,}\b", content_lower))
                matches = words.intersection(doc_words)

                if not matches:
                    continue

                score = len(matches) * 3.0
                doc_title = str(r[4] or "")
                doc_type = str(r[3] or "")
                title_lower = doc_title.lower()
                title_words = set(re.findall(r"\b[a-zA-Z0-9.%]{3,}\b", title_lower))
                title_matches = words.intersection(title_words)
                score += len(title_matches) * 5.0

                pub_date = str(r[7] or "")
                if "2026" in pub_date:
                    score += 3.0
                    if "Factsheet" in doc_title:
                        score += 5.0
                elif "2025" in pub_date:
                    score += 0.5

                # Recency & Factsheet priority for current financial metrics (TER, Expense Ratio, NAV, AUM)
                if ("Factsheet" in doc_title or doc_type == "Factsheet") and words.intersection({"expense", "ratio", "ter", "nav", "portfolio", "turnover", "aum"}):
                    score += 20.0

                if score > 0:
                    scored.append({
                        "chunk_id": r[0],
                        "text": r[1],
                        "scheme_name": r[2],
                        "document_type": r[3],
                        "document_title": r[4],
                        "source_id": r[5],
                        "source_url": r[6],
                        "published_date": r[7] or "Date not available",
                        "accessed_date": r[8] or "Date not available",
                        "page_number": int(r[9]),
                        "metadata": r[10] if isinstance(r[10], dict) else {},
                        "distance": 0.0,
                        "relevance_score": score,
                    })

            scored.sort(key=lambda x: (x["relevance_score"], str(x.get("published_date", ""))), reverse=True)
            return scored[:top_k]

        except Exception as e:
            logger.error(f"Fallback keyword search failed on Neon: {e}", exc_info=True)
            return []

    def query_relevant_chunks(
        self,
        query: str,
        n_results: int = 5,
        scheme_filter: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Backward compatibility alias for retrieve()."""
        return self.retrieve(query=query, n_results=n_results, scheme_filter=scheme_filter)
