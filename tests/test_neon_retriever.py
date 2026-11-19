"""
Test suite for Neon PostgreSQL & pgvector integration:
- Database connection and extension validation
- 3072-dimension vector integrity
- Semantic retrieval and scheme isolation
- Citation metadata completeness
- Idempotent upsert verification
- Keyword/BM25 fallback on API failure
- Empty database behavior
"""

import pytest
import psycopg
from pgvector.psycopg import register_vector
from src.config import config
from src.neon_retriever import NeonRetriever
from src.llm import GeminiClient


class FailingEmbedLLM(GeminiClient):
    """Mock LLM client that simulates embedding API exhaustion."""

    def __init__(self):
        super().__init__()

    def is_available(self) -> bool:
        return True

    def embed_text(self, text: str):
        raise RuntimeError("429 RESOURCE_EXHAUSTED: Embed content requests per day limit exceeded.")


class MockVectorLLM(GeminiClient):
    """Mock LLM client returning deterministic 3072-dim vectors for fast offline tests."""

    def __init__(self, vector=None):
        super().__init__()
        self.vector = vector or [0.01] * 3072

    def is_available(self) -> bool:
        return True

    def embed_text(self, text: str):
        return self.vector


@pytest.fixture(scope="module")
def neon_retriever():
    if not config.is_db_configured():
        pytest.skip("DATABASE_URL not configured in environment")
    return NeonRetriever()


class TestNeonDatabaseIntegrity:
    """Tests for Neon PostgreSQL schema, pgvector extension, and dimensions."""

    def test_database_connection(self):
        """Verify active connection to Neon PostgreSQL."""
        assert config.is_db_configured(), "DATABASE_URL must be configured"
        with psycopg.connect(config.DATABASE_URL) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1;")
                assert cur.fetchone()[0] == 1

    def test_pgvector_extension_and_halfvec(self):
        """Verify vector extension and halfvec support."""
        with psycopg.connect(config.DATABASE_URL) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT extversion FROM pg_extension WHERE extname = 'vector';")
                row = cur.fetchone()
                assert row is not None, "pgvector extension must be installed"
                assert tuple(map(int, row[0].split(".")[:2])) >= (0, 7)

    def test_documents_table_and_indexes(self):
        """Verify documents table exists with required indexes."""
        with psycopg.connect(config.DATABASE_URL) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT to_regclass('public.documents');")
                assert cur.fetchone()[0] is not None, "documents table must exist"

                # Check index existence
                cur.execute("""
                    SELECT indexname FROM pg_indexes 
                    WHERE tablename = 'documents';
                """)
                indexes = [r[0] for r in cur.fetchall()]
                assert "idx_documents_embedding_hnsw" in indexes
                assert "idx_documents_scheme" in indexes
                assert "idx_documents_source" in indexes

    def test_vector_dimensions_exact_3072(self):
        """Verify all indexed embeddings have exact dimension of 3072."""
        with psycopg.connect(config.DATABASE_URL) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT DISTINCT vector_dims(embedding) FROM documents;")
                dims = [r[0] for r in cur.fetchall()]
                assert dims == [3072], f"All embeddings must have dimension 3072, found {dims}"


class TestNeonRetrievalAndFilters:
    """Tests for semantic search, scheme isolation, and citation metadata."""

    def test_retriever_is_indexed(self, neon_retriever):
        """Retriever must report indexed status when records exist."""
        assert neon_retriever.is_indexed() is True

    def test_scheme_isolation(self, neon_retriever):
        """Filtering by HDFC Flexi Cap Fund must never return HDFC Nifty 50 chunks."""
        chunks = neon_retriever.retrieve(
            query="What is the benchmark index?",
            n_results=5,
            scheme_filter="HDFC Flexi Cap Fund"
        )
        assert len(chunks) > 0
        for c in chunks:
            assert "Nifty 50 Index Fund" not in c["document_title"], "Nifty 50 leaked into Flexi Cap retrieval"
            assert c["scheme_name"] in ["HDFC Flexi Cap Fund", "General / Portfolio Facts"]

    def test_citation_metadata_completeness(self, neon_retriever):
        """Every retrieved chunk must contain complete official citation metadata."""
        chunks = neon_retriever.retrieve(
            query="What is the lock-in period for HDFC ELSS Tax Saver Fund?",
            n_results=5
        )
        assert len(chunks) > 0
        for c in chunks:
            assert c["chunk_id"], "chunk_id must not be empty"
            assert c["text"], "chunk text must not be empty"
            assert c["source_url"].startswith("https://"), "source_url must be HTTPS"
            assert "hdfcfund.com" in c["source_url"], "source_url must point to hdfcfund.com"
            assert c["document_title"], "document_title must not be empty"
            assert c["page_number"] >= 1, "page_number must be valid"
            assert c["published_date"], "published_date must be populated"

    def test_statement_download_retrieval(self, neon_retriever):
        """Statement download query must retrieve the official statement guide."""
        chunks = neon_retriever.retrieve(
            query="How can I download my mutual fund account statement?",
            n_results=5
        )
        assert len(chunks) > 0
        guide_chunks = [c for c in chunks if "Statement & CAS Download Guide" in c["document_title"]]
        assert len(guide_chunks) > 0, "Statement Download Guide must be in retrieved chunks"
        assert guide_chunks[0]["page_number"] == 1


class TestNeonResilienceAndEdgeCases:
    """Tests for keyword fallback, idempotency, and empty database behavior."""

    def test_fallback_keyword_retrieve_on_api_exhaustion(self):
        """When embedding API fails, retriever must use keyword fallback seamlessly."""
        retriever = NeonRetriever(llm_client=FailingEmbedLLM())
        chunks = retriever.retrieve("What is the expense ratio of HDFC Flexi Cap Fund?", n_results=5)
        assert len(chunks) > 0
        # Must still find Factsheet
        factsheet_chunks = [c for c in chunks if "Factsheet" in c["document_title"]]
        assert len(factsheet_chunks) > 0, "Keyword fallback must retrieve factsheet for expense ratio query"
        assert factsheet_chunks[0]["source_url"].startswith("https://")

    def test_idempotent_upsert(self):
        """Inserting an existing chunk_id must update without creating duplicate rows."""
        with psycopg.connect(config.DATABASE_URL) as conn:
            register_vector(conn)
            with conn.cursor() as cur:
                # Count before
                cur.execute("SELECT COUNT(*) FROM documents;")
                count_before = cur.fetchone()[0]

                # Re-upsert a known chunk
                sample_sql = """
                    INSERT INTO documents (
                        chunk_id, content, scheme_name, document_type, document_title,
                        source_id, source_url, published_date, accessed_date, page_number,
                        metadata, embedding
                    ) VALUES (
                        %(chunk_id)s, %(content)s, %(scheme_name)s, %(document_type)s, %(document_title)s,
                        %(source_id)s, %(source_url)s, %(published_date)s, %(accessed_date)s, %(page_number)s,
                        %(metadata)s, %(embedding)s
                    )
                    ON CONFLICT (chunk_id) DO UPDATE SET
                        content = EXCLUDED.content;
                """
                dummy_params = {
                    "chunk_id": "hdfc_common_transaction_form_p1_c0",
                    "content": "Updated content for idempotency test",
                    "scheme_name": "General Account Operations",
                    "document_type": "Service_Form",
                    "document_title": "Common Transaction Form - Non Financial Transactions",
                    "source_id": "hdfc_common_transaction_form",
                    "source_url": "https://files.hdfcfund.com/sample.pdf",
                    "published_date": "2026-11-05",
                    "accessed_date": "2026-11-19",
                    "page_number": 1,
                    "metadata": "{}",
                    "embedding": [0.01] * 3072,
                }
                cur.execute(sample_sql, dummy_params)
                conn.commit()

                # Count after
                cur.execute("SELECT COUNT(*) FROM documents;")
                count_after = cur.fetchone()[0]
                assert count_before == count_after, "Idempotent insert must not increment total row count"

    def test_empty_scheme_behavior(self, neon_retriever):
        """Querying for a non-existent scheme must return empty list without crashing."""
        chunks = neon_retriever.retrieve(
            query="What is the NAV?",
            scheme_filter="NonExistentSchemeXYZ"
        )
        assert chunks == []
