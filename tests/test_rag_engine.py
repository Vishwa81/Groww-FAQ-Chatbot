"""
Comprehensive test suite for Phase 2 RAG Engine:
- Guardrail classification: factual, advisory, comparison, unsupported, PII
- PII detection and redaction (ensuring sensitive values are never echoed)
- Retrieval with scheme filtering and date precedence
- 3-sentence answer constraint
- Missing context handling and no fabricated citations
"""

import pytest
from src.guardrails import (
    GuardrailEngine,
    QueryIntent,
    EDUCATIONAL_RESOURCE_URL,
    GROWW_HELP_URL,
)
from src.retriever import ChromaRetriever, detect_scheme_from_query
from src.response import FAQResponseService, count_and_limit_sentences
from src.llm import GeminiClient


class MockLLMClient(GeminiClient):
    """Mock Gemini client for deterministic offline testing."""

    def __init__(self, mock_response: str = "This is sentence one. This is sentence two. This is sentence three."):
        self.mock_response = mock_response

    def is_available(self) -> bool:
        return True

    def generate_answer(self, prompt: str, system_instruction: str = None) -> str:
        return self.mock_response

    def embed_text(self, text: str):
        # Deterministic 3072-dim vector
        return [0.05] * 3072


class MockRetriever:
    """Mock retriever for controlled unit testing."""

    def __init__(self, return_chunks=None):
        self.return_chunks = return_chunks or []

    def is_indexed(self) -> bool:
        return True

    def retrieve(self, query: str, n_results: int = 5, scheme_filter: str = None):
        return self.return_chunks


class TestGuardrailsRAG:
    """Tests for guardrail classifications and PII privacy."""

    @pytest.mark.parametrize("query", [
        "What is the expense ratio of HDFC Flexi Cap Fund?",
        "What is the lock-in period of HDFC ELSS Tax Saver Fund?",
        "How can I download my mutual fund account statement?",
        "What is the benchmark of HDFC Nifty 50 Index Fund?",
    ])
    def test_factual_query_classification(self, query: str):
        intent, refusal, link = GuardrailEngine.classify_query(query)
        assert intent == QueryIntent.FACTUAL_QUERY
        assert refusal == ""
        assert link is None

    @pytest.mark.parametrize("query", [
        "Should I buy this fund?",
        "Should I sell my investments?",
        "Which mutual fund is best?",
        "Which fund will generate higher returns?",
        "Where should I invest 10000 rupees?",
        "Can you suggest a good portfolio allocation?",
    ])
    def test_investment_advice_refusal(self, query: str):
        intent, refusal, link = GuardrailEngine.classify_query(query)
        assert intent == QueryIntent.INVESTMENT_ADVICE
        assert "cannot provide investment advice" in refusal
        assert link == EDUCATIONAL_RESOURCE_URL

    @pytest.mark.parametrize("query", [
        "Compare the returns of HDFC Flexi Cap and HDFC Nifty 50",
        "Which fund will give higher returns next year?",
        "Will HDFC Nifty 50 double my money in 5 years?",
        "Which fund beats the market?",
    ])
    def test_performance_comparison_refusal(self, query: str):
        intent, refusal, link = GuardrailEngine.classify_query(query)
        assert intent == QueryIntent.PERFORMANCE_COMPARISON
        assert "cannot compare mutual fund performance" in refusal
        assert link == EDUCATIONAL_RESOURCE_URL

    @pytest.mark.parametrize("query", [
        "What is the NAV of SBI Bluechip Fund?",
        "What is the expense ratio of ICICI Prudential Fund?",
        "Who won the cricket match yesterday?",
    ])
    def test_unsupported_query_refusal(self, query: str):
        intent, refusal, link = GuardrailEngine.classify_query(query)
        assert intent == QueryIntent.UNSUPPORTED_QUERY
        assert len(refusal) > 0
        assert link in [GROWW_HELP_URL, EDUCATIONAL_RESOURCE_URL]

    @pytest.mark.parametrize("pii_query, expected_redaction", [
        ("My PAN is ABCDE1234F, what is my folio?", "[REDACTED_PAN]"),
        ("Here is my Aadhaar 1234 5678 9012 please check", "[REDACTED_AADHAAR]"),
        ("Contact me at user@test.com", "[REDACTED_EMAIL]"),
        ("My phone number is 9876543210", "[REDACTED_PHONE]"),
        ("My bank account is account 123456789012", "[REDACTED_ACCOUNT]"),
        ("My secret otp is 849201", "[REDACTED_OTP]"),
    ])
    def test_pii_detection_and_redaction(self, pii_query: str, expected_redaction: str):
        assert GuardrailEngine.detect_pii(pii_query) is True
        intent, refusal, link = GuardrailEngine.classify_query(pii_query)
        assert intent == QueryIntent.PII_REQUEST_OR_DISCLOSURE
        assert "does not collect, process, or store personal identifiers" in refusal
        assert link == GROWW_HELP_URL

        # Ensure PII values are redacted and never echoed
        redacted = GuardrailEngine.redact_pii(pii_query)
        assert expected_redaction in redacted
        for original_val in ["ABCDE1234F", "1234 5678 9012", "user@test.com", "9876543210", "849201"]:
            assert original_val not in redacted


class TestResponseFormattingAndConstraints:
    """Tests for 3-sentence limits, citation verification, and missing context."""

    def test_sentence_limiter(self):
        five_sentences = "Sentence one. Sentence two! Sentence three? Sentence four. Sentence five."
        limited = count_and_limit_sentences(five_sentences, max_sentences=3)
        assert limited == "Sentence one. Sentence two! Sentence three?"

        two_sentences = "Sentence one. Sentence two."
        assert count_and_limit_sentences(two_sentences, max_sentences=3) == two_sentences

    def test_missing_retrieval_context(self):
        empty_retriever = MockRetriever(return_chunks=[])
        service = FAQResponseService(retriever=empty_retriever, llm_client=MockLLMClient())

        res = service.process_query("What is the expense ratio?")
        assert res["status"] == "no_context"
        assert "could not be verified from the available official sources" in res["answer_body"]
        assert res["last_updated"] == "Date not available"

    def test_no_fabricated_citations(self):
        verified_url = "https://files.hdfcfund.com/s3fs-public/SID/test.pdf"
        mock_chunks = [{
            "chunk_id": "c1",
            "text": "The Total Expense Ratio is 0.85% as of September 2026.",
            "source_url": verified_url,
            "document_title": "HDFC Flexi Cap SID",
            "page_number": 22,
            "scheme_name": "HDFC Flexi Cap Fund",
            "document_type": "SID",
            "published_date": "2025-11-21",
            "distance": 0.2,
        }]

        mock_llm = MockLLMClient("The expense ratio is 0.85%. It is calculated on daily net assets.")
        service = FAQResponseService(retriever=MockRetriever(return_chunks=mock_chunks), llm_client=mock_llm)

        res = service.process_query("What is the expense ratio of HDFC Flexi Cap Fund?")
        assert res["status"] == "success"
        assert res["source_link"] == verified_url
        assert res["document_title"] == "HDFC Flexi Cap SID"
        assert res["page_number"] == 22
        assert "2025-11-21" in res["last_updated"]

    def test_conflicting_document_dates(self):
        mock_chunks = [
            {
                "chunk_id": "c_old",
                "text": "TER was 0.90% previously.",
                "source_url": "https://files.hdfcfund.com/old.pdf",
                "document_title": "Old SID",
                "page_number": 10,
                "scheme_name": "HDFC Flexi Cap Fund",
                "document_type": "SID",
                "published_date": "2025-11-21",
                "distance": 0.25,
            },
            {
                "chunk_id": "c_new",
                "text": "TER is 0.85% as per factsheet.",
                "source_url": "https://files.hdfcfund.com/new.pdf",
                "document_title": "New Factsheet",
                "page_number": 5,
                "scheme_name": "HDFC Flexi Cap Fund",
                "document_type": "Factsheet",
                "published_date": "2026-09-30",
                "distance": 0.20,
            }
        ]

        # Service sorts chunks by date descending
        service = FAQResponseService(retriever=MockRetriever(return_chunks=mock_chunks), llm_client=MockLLMClient())
        res = service.process_query("What is the latest expense ratio?")
        assert "2026-09-30" in res["last_updated"]
        assert "2025-11-21" in res["last_updated"]


class TestRetrievalIntegration:
    """Integration tests on live ChromaDB vector store."""

    def test_scheme_intent_detection(self):
        assert detect_scheme_from_query("What is the lock-in for HDFC ELSS Tax Saver Fund?") == "HDFC ELSS Tax Saver Fund"
        assert detect_scheme_from_query("What is the expense ratio of HDFC Flexi Cap?") == "HDFC Flexi Cap Fund"
        assert detect_scheme_from_query("What is HDFC Nifty 50 Index Fund?") == "HDFC Nifty 50 Index Fund"
        assert detect_scheme_from_query("How to download statement?") == "General Account Operations"
        assert detect_scheme_from_query("What is the general NAV cutoff time?") is None

    def test_live_chromadb_scheme_isolation(self):
        retriever = ChromaRetriever(llm_client=MockLLMClient())
        if not retriever.is_indexed():
            pytest.skip("ChromaDB not indexed yet")

        # Query with explicit filter for Nifty 50
        chunks = retriever.retrieve(
            query="What is the expense ratio?",
            n_results=5,
            scheme_filter="HDFC Nifty 50 Index Fund"
        )
        assert len(chunks) > 0
        for c in chunks:
            assert c["scheme_name"] == "HDFC Nifty 50 Index Fund"
            assert "Flexi Cap" not in c["scheme_name"]
            assert "ELSS" not in c["scheme_name"]
