"""
Unit tests for ChromaDB retrieval component.
Verifies initial unindexed state and query handling without raising unexpected exceptions.
"""

from src.retriever import ChromaRetriever


class TestChromaRetriever:
    """Test suite for retrieval safety and initial state."""

    def test_retriever_initialization(self, tmp_path):
        retriever = ChromaRetriever(persist_dir=tmp_path / "chroma_test")
        assert retriever.is_indexed() is False
        assert retriever.get_document_count() == 0

    def test_query_unindexed_retriever_returns_empty(self, tmp_path):
        retriever = ChromaRetriever(persist_dir=tmp_path / "chroma_test")
        results = retriever.query_relevant_chunks("What is the expense ratio?", n_results=3)
        assert isinstance(results, list)
        assert len(results) == 0
