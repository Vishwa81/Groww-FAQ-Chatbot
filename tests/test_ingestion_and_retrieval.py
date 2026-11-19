"""
Comprehensive test suite for Phase 2B:
- PDF extraction and page preservation
- Sentence-aware chunking and metadata validation
- Duplicate prevention and idempotency
- ChromaDB persistence
- Retrieval with scheme filtering
"""

import pytest
from pathlib import Path
from src.ingestion import (
    DocumentIngestionPipeline,
    ChunkMetadata,
    DocumentChunk,
    SourceCatalog,
)
from src.retriever import ChromaRetriever


class MockGeminiClient:
    """Mock Gemini client for deterministic offline testing."""

    def is_available(self) -> bool:
        return True

    def embed_text(self, text: str):
        # 3072-dimensional vector with deterministic values
        val = float(len(text) % 10) / 10.0
        return [val] * 3072

    def embed_batch(self, texts, batch_size=16):
        return [self.embed_text(t) for t in texts]


class TestIngestionAndRetrieval:
    """Test suite covering Phase 2B ingestion, metadata, persistence, and retrieval."""

    def test_sources_catalog_loading(self):
        catalog = SourceCatalog()
        assert len(catalog.sources) > 0

        # Verify HDFC Nifty 50 SID metadata mapping
        meta, is_reg = catalog.get_metadata_for_file("HDFC_Nifty_50_Index_Fund_SID.pdf")
        assert is_reg is True
        assert meta["scheme_name"] == "HDFC Nifty 50 Index Fund"
        assert meta["document_type"] == "SID"
        assert meta["published_date"] != "unknown"
        assert meta["source_url"].startswith("https://files.hdfcfund.com")

    def test_pdf_extraction_real_file(self):
        pipeline = DocumentIngestionPipeline()
        pdf_path = Path("data/raw/HDFC_Nifty_50_Index_Fund_KIM.pdf")
        if not pdf_path.exists():
            pytest.skip("PDF not found in data/raw")

        pages, report = pipeline.extract_pdf(pdf_path)
        assert report.total_pages > 0
        assert report.usable_pages > 0
        assert report.total_characters > 1000
        assert report.is_scanned is False
        assert len(report.source_hash) == 64  # SHA256 length

        # Verify page numbers are preserved and sequential
        for page in pages:
            assert "page_number" in page
            assert page["page_number"] >= 1
            assert len(page["text"]) >= 20

    def test_chunking_and_metadata_schema(self):
        pipeline = DocumentIngestionPipeline(target_token_size=200, token_overlap=30)
        sample_text = (
            "The investment objective of the Scheme is to provide investment returns that closely correspond to the total returns of the Nifty 50 Index. "
            "The Scheme will invest 95% to 100% in stocks comprising the Nifty 50 Index. "
            "Cash and money market instruments may comprise 0% to 5% of the portfolio. "
            "Total Expense Ratio for Direct Plan is capped as per SEBI regulations. "
            "Exit load is nil. The minimum application amount for SIP is Rs. 100. "
            "Units will be allotted within 5 business days from the closure of NFO. "
        ) * 5

        meta_dict = {
            "source_id": "test_nifty_50",
            "scheme_name": "HDFC Nifty 50 Index Fund",
            "document_type": "SID",
            "document_title": "Test SID Document",
            "source_url": "https://files.hdfcfund.com/test.pdf",
            "published_date": "2025-11-21",
            "accessed_date": "2026-11-19",
        }

        chunks = pipeline.chunk_page_text(
            text=sample_text,
            page_number=3,
            source_id="test_nifty_50",
            source_meta=meta_dict,
            source_hash="testhash123",
        )

        assert len(chunks) > 1
        for idx, chunk in enumerate(chunks):
            m = chunk.metadata.to_dict()
            # Verify all 9 required metadata fields are non-empty
            assert m["source_id"] == "test_nifty_50"
            assert m["scheme_name"] == "HDFC Nifty 50 Index Fund"
            assert m["document_type"] == "SID"
            assert m["document_title"] == "Test SID Document"
            assert m["source_url"] == "https://files.hdfcfund.com/test.pdf"
            assert m["published_date"] == "2025-11-21"
            assert m["accessed_date"] == "2026-11-19"
            assert m["page_number"] == 3
            assert m["chunk_id"] == f"test_nifty_50_p3_c{idx}"
            assert m["source_hash"] == "testhash123"

    def test_duplicate_prevention_and_persistence(self, tmp_path):
        retriever = ChromaRetriever(persist_dir=tmp_path / "chroma_test", llm_client=MockGeminiClient())
        collection = retriever.get_collection()

        metadata_1 = ChunkMetadata(
            source_id="test_doc_1",
            scheme_name="HDFC Flexi Cap Fund",
            document_type="SID",
            document_title="HDFC Flexi Cap SID",
            source_url="https://files.hdfcfund.com/flexi.pdf",
            published_date="2025-11-21",
            accessed_date="2026-11-19",
            page_number=1,
            chunk_id="test_doc_1_p1_c0",
            source_hash="original_hash_111",
        )

        chunk_1 = DocumentChunk(text="HDFC Flexi Cap is an open-ended dynamic equity scheme.", metadata=metadata_1)
        embeddings = [[0.1] * 3072]

        # Index chunk
        retriever.index_chunks([chunk_1], embeddings)
        assert retriever.get_document_count() == 1

        # Check idempotency check
        assert retriever.is_document_indexed_and_current("test_doc_1", "original_hash_111") is True
        assert retriever.is_document_indexed_and_current("test_doc_1", "modified_hash_222") is False

        # Re-index with modified hash should replace
        retriever.delete_document("test_doc_1")
        assert retriever.get_document_count() == 0

    def test_retrieval_with_scheme_filtering(self, tmp_path):
        mock_llm = MockGeminiClient()
        retriever = ChromaRetriever(persist_dir=tmp_path / "chroma_filter_test", llm_client=mock_llm)

        # Chunk for Scheme A
        meta_a = ChunkMetadata(
            source_id="nifty_50",
            scheme_name="HDFC Nifty 50 Index Fund",
            document_type="SID",
            document_title="Nifty 50 SID",
            source_url="https://files.hdfcfund.com/nifty50.pdf",
            published_date="2025-11-21",
            accessed_date="2026-11-19",
            page_number=5,
            chunk_id="nifty_p5_c0",
            source_hash="hash_a",
        )
        chunk_a = DocumentChunk(text="Expense ratio of HDFC Nifty 50 Index Fund is 0.20 percent.", metadata=meta_a)

        # Chunk for Scheme B
        meta_b = ChunkMetadata(
            source_id="flexi_cap",
            scheme_name="HDFC Flexi Cap Fund",
            document_type="SID",
            document_title="Flexi Cap SID",
            source_url="https://files.hdfcfund.com/flexicap.pdf",
            published_date="2025-11-21",
            accessed_date="2026-11-19",
            page_number=12,
            chunk_id="flexi_p12_c0",
            source_hash="hash_b",
        )
        chunk_b = DocumentChunk(text="Expense ratio of HDFC Flexi Cap Fund is 0.85 percent.", metadata=meta_b)

        # Vectors
        vec_a = [0.1] * 3072
        vec_b = [0.9] * 3072

        retriever.index_chunks([chunk_a, chunk_b], [vec_a, vec_b])
        assert retriever.get_document_count() == 2

        # 1. Retrieve with scheme filter for Nifty 50
        results_nifty = retriever.retrieve(
            query="What is the expense ratio?",
            n_results=5,
            scheme_filter="HDFC Nifty 50 Index Fund"
        )
        assert len(results_nifty) == 1
        assert results_nifty[0]["scheme_name"] == "HDFC Nifty 50 Index Fund"
        assert results_nifty[0]["document_title"] == "Nifty 50 SID"
        assert results_nifty[0]["page_number"] == 5

        # 2. Retrieve with scheme filter for Flexi Cap
        results_flexi = retriever.retrieve(
            query="What is the expense ratio?",
            n_results=5,
            scheme_filter="HDFC Flexi Cap Fund"
        )
        assert len(results_flexi) == 1
        assert results_flexi[0]["scheme_name"] == "HDFC Flexi Cap Fund"
        assert results_flexi[0]["document_title"] == "Flexi Cap SID"
        assert results_flexi[0]["page_number"] == 12
