"""
Retriever module for Groww Mutual Fund FAQ Assistant.
Manages ChromaDB vector database collections (hdfc_mutual_fund_knowledge),
document indexing with duplicate prevention, and semantic similarity search with scheme filtering,
relevance thresholds, and date precedence.
"""

from typing import List, Dict, Any, Optional
from pathlib import Path
import logging
from src.config import config
from src.ingestion import DocumentChunk
from src.llm import GeminiClient

logger = logging.getLogger(__name__)


def detect_scheme_from_query(query: str) -> Optional[str]:
    """Detect specific HDFC scheme intent from query text for targeted filtering."""
    q = query.lower()
    if "nifty 50" in q or "nifty50" in q:
        return "HDFC Nifty 50 Index Fund"
    if "flexi cap" in q or "flexicap" in q:
        return "HDFC Flexi Cap Fund"
    if "elss" in q or "tax saver" in q or "taxsaver" in q:
        return "HDFC ELSS Tax Saver Fund"
    if "statement" in q or "cas" in q or ("download" in q and "fund" not in q):
        return "General Account Operations"
    return None


class ChromaRetriever:
    """Vector database retrieval engine backed by ChromaDB and Gemini embeddings."""

    COLLECTION_NAME = config.CHROMA_COLLECTION_NAME

    def __init__(
        self,
        persist_dir: Optional[Path] = None,
        llm_client: Optional[GeminiClient] = None,
    ):
        self.persist_dir = persist_dir or config.CHROMA_PERSIST_DIR
        self.llm = llm_client or GeminiClient()
        self._client = None
        self._collection = None

    def _get_client(self):
        """Lazy initialization of ChromaDB persistent client."""
        if self._client is None:
            try:
                import chromadb
                self.persist_dir.mkdir(parents=True, exist_ok=True)
                self._client = chromadb.PersistentClient(path=str(self.persist_dir))
            except ImportError:
                logger.warning("chromadb is not installed. Vector retrieval is disabled.")
                return None
        return self._client

    def get_collection(self):
        """Retrieve or create the ChromaDB collection."""
        client = self._get_client()
        if client is None:
            return None

        if self._collection is None:
            self._collection = client.get_or_create_collection(
                name=self.COLLECTION_NAME,
                metadata={"description": "Official HDFC Mutual Fund Knowledge Base for FAQ Assistant"}
            )
        return self._collection

    def is_indexed(self) -> bool:
        """Check if vector collection exists and contains indexed documents."""
        try:
            collection = self.get_collection()
            if collection is None:
                return False
            return collection.count() > 0
        except Exception as e:
            logger.debug(f"Vector store index check failed: {e}")
            return False

    def get_document_count(self) -> int:
        """Return the number of indexed chunks."""
        try:
            collection = self.get_collection()
            if collection:
                return collection.count()
        except Exception:
            pass
        return 0

    def is_document_indexed_and_current(self, source_id: str, source_hash: str) -> bool:
        """
        Check if a document is already indexed with an identical content hash.
        Used to prevent redundant API calls and duplicate indexing.
        """
        collection = self.get_collection()
        if collection is None or collection.count() == 0:
            return False

        try:
            existing = collection.get(
                where={"source_id": str(source_id)},
                limit=1,
                include=["metadatas"]
            )
            if existing and existing.get("metadatas") and len(existing["metadatas"]) > 0:
                stored_hash = existing["metadatas"][0].get("source_hash")
                return stored_hash == source_hash
        except Exception as e:
            logger.debug(f"Error checking document status for {source_id}: {e}")
        return False

    def delete_document(self, source_id: str) -> int:
        """Delete all chunks associated with a source_id to enable clean reindexing."""
        collection = self.get_collection()
        if collection is None or collection.count() == 0:
            return 0

        try:
            existing = collection.get(
                where={"source_id": str(source_id)},
                include=["metadatas"]
            )
            count = len(existing.get("ids", []))
            if count > 0:
                collection.delete(where={"source_id": str(source_id)})
                logger.info(f"Deleted {count} existing chunks for source_id: {source_id}")
            return count
        except Exception as e:
            logger.error(f"Error deleting chunks for {source_id}: {e}")
            return 0

    def index_chunks(
        self,
        chunks: List[DocumentChunk],
        embeddings: List[List[float]],
    ) -> int:
        """
        Store chunks, embeddings, and metadata in ChromaDB.
        Avoids duplicates by checking chunk_ids and reindexing where appropriate.
        """
        if not chunks or not embeddings or len(chunks) != len(embeddings):
            raise ValueError("Chunks and embeddings must be non-empty and have matching lengths.")

        collection = self.get_collection()
        if collection is None:
            raise RuntimeError("ChromaDB collection is unavailable.")

        ids = [chunk.chunk_id for chunk in chunks]
        texts = [chunk.text for chunk in chunks]
        metadatas = [chunk.metadata.to_dict() for chunk in chunks]

        # ChromaDB supports batch upsert
        collection.upsert(
            ids=ids,
            embeddings=embeddings,
            metadatas=metadatas,
            documents=texts,
        )
        return len(chunks)

    def retrieve(
        self,
        query: str,
        n_results: int = 5,
        scheme_filter: Optional[str] = None,
        relevance_threshold: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        """
        Semantic vector retrieval with scheme filtering, relevance cutoff, and date sorting.
        Accepts user question, embeds query with gemini-embedding-001,
        and returns matching chunks with verified metadata.
        """
        collection = self.get_collection()
        if collection is None or collection.count() == 0:
            return []

        # Enforce maximum of 5 chunks for final retrieval
        top_k = min(max(1, n_results), 5)
        # Fetch a wider candidate pool from vector store to allow recency precedence sorting
        candidate_k = min(max(15, top_k * 3), 25)

        # Automatic scheme detection if not explicitly passed
        active_scheme_filter = scheme_filter or detect_scheme_from_query(query)
        where_filter = None
        if active_scheme_filter:
            where_filter = {"scheme_name": active_scheme_filter}

        # Generate embedding for user question with automatic fallback on quota exhaustion
        try:
            query_vector = self.llm.embed_text(query)
        except Exception as e:
            logger.warning(f"Vector embedding unavailable ({e}). Using resilient keyword retrieval fallback.")
            return self._fallback_keyword_retrieve(query, active_scheme_filter, top_k)

        try:
            results = collection.query(
                query_embeddings=[query_vector],
                n_results=candidate_k,
                where=where_filter,
                include=["documents", "metadatas", "distances"],
            )

            retrieved = []
            if results and results.get("documents"):
                documents = results["documents"][0]
                metadatas = results["metadatas"][0] if results.get("metadatas") else [{}] * len(documents)
                distances = results["distances"][0] if results.get("distances") else [0.0] * len(documents)
                ids = results["ids"][0] if results.get("ids") else [""] * len(documents)

                for doc_id, doc_text, meta, dist in zip(ids, documents, metadatas, distances):
                    # Filter out chunks exceeding relevance distance threshold if specified
                    if relevance_threshold is not None and dist > relevance_threshold:
                        logger.debug(f"Filtering out chunk {doc_id} with distance {dist:.3f} > {relevance_threshold}")
                        continue

                    retrieved.append({
                        "chunk_id": doc_id,
                        "text": doc_text,
                        "source_url": meta.get("source_url", "unknown"),
                        "document_title": meta.get("document_title", "unknown"),
                        "page_number": int(meta.get("page_number", 1)),
                        "scheme_name": meta.get("scheme_name", "unknown"),
                        "document_type": meta.get("document_type", "unknown"),
                        "published_date": meta.get("published_date", "Date not available"),
                        "accessed_date": meta.get("accessed_date", "Date not available"),
                        "distance": dist,
                        "metadata": meta,
                    })

            # Calculate composite ranking score combining semantic relevance and recency precedence
            # Semantic similarity = (1.0 - dist)
            # Recency boost gives appropriate precedence to latest applicable monthly disclosures
            for item in retrieved:
                dist = item.get("distance", 1.0)
                sim = max(0.0, 1.0 - dist)
                pub_date = str(item.get("published_date", ""))
                doc_title = str(item.get("document_title", ""))

                recency_boost = 0.0
                if "2026" in pub_date:
                    recency_boost += 0.12
                    if "Factsheet" in doc_title:
                        recency_boost += 0.08
                elif "2025" in pub_date:
                    recency_boost += 0.02

                item["relevance_score"] = sim + recency_boost

            retrieved.sort(key=lambda x: x["relevance_score"], reverse=True)
            return retrieved[:top_k]
        except Exception as e:
            logger.error(f"Error querying ChromaDB collection: {e}")
            return self._fallback_keyword_retrieve(query, active_scheme_filter, top_k)

    def _fallback_keyword_retrieve(
        self,
        query: str,
        scheme_filter: Optional[str] = None,
        top_k: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        Resilient keyword retrieval fallback when external embedding API hits rate or daily quota limits.
        Searches indexed ChromaDB documents with BM25-style term weighting and recency boosts.
        """
        collection = self.get_collection()
        if collection is None or collection.count() == 0:
            return []

        import re
        stopwords = {
            "about", "after", "again", "all", "also", "and", "any", "are", "been", "both", "but",
            "can", "each", "few", "for", "from", "had", "has", "have", "how", "into", "its",
            "more", "most", "not", "our", "out", "she", "some", "such", "than", "that", "the",
            "their", "them", "then", "there", "these", "they", "this", "those", "was", "were",
            "what", "when", "where", "which", "who", "will", "with", "would", "you", "your"
        }
        words = set(re.findall(r"\b[a-zA-Z0-9.%]{3,}\b", query.lower())) - stopwords
        where_filter = {"scheme_name": scheme_filter} if scheme_filter else None

        try:
            records = collection.get(where=where_filter, include=["documents", "metadatas"])
            if not records or not records.get("documents"):
                return []

            scored = []
            for doc_id, doc_text, meta in zip(records["ids"], records["documents"], records["metadatas"]):
                doc_lower = doc_text.lower()
                doc_words = set(re.findall(r"\b[a-zA-Z0-9.%]{3,}\b", doc_lower))
                matches = words.intersection(doc_words)

                score = len(matches) * 3.0
                pub_date = str(meta.get("published_date", ""))
                doc_title = str(meta.get("document_title", ""))

                if "2026" in pub_date:
                    score += 2.0
                    if "Factsheet" in doc_title:
                        score += 3.0
                elif "2025" in pub_date:
                    score += 0.5

                if score > 0:
                    scored.append({
                        "chunk_id": doc_id,
                        "text": doc_text,
                        "source_url": meta.get("source_url", "unknown"),
                        "document_title": meta.get("document_title", "unknown"),
                        "page_number": int(meta.get("page_number", 1)),
                        "scheme_name": meta.get("scheme_name", "unknown"),
                        "document_type": meta.get("document_type", "unknown"),
                        "published_date": meta.get("published_date", "Date not available"),
                        "accessed_date": meta.get("accessed_date", "Date not available"),
                        "distance": 0.0,
                        "relevance_score": score,
                        "metadata": meta,
                    })

            scored.sort(key=lambda x: (x["relevance_score"], str(x.get("published_date", ""))), reverse=True)
            return scored[:top_k]
        except Exception as e:
            logger.error(f"Fallback retrieval failed: {e}")
            return []

    def query_relevant_chunks(
        self,
        query: str,
        n_results: int = 5,
        scheme_filter: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Alias for retrieve() to ensure backward compatibility."""
        return self.retrieve(query=query, n_results=n_results, scheme_filter=scheme_filter)
