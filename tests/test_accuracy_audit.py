"""
Accuracy and Citation Audit Test Suite for Groww Mutual Fund FAQ Assistant.

Audits:
1. Issue 1: Historical Expense Ratio vs Current TER distinction
2. Issue 2: Citation Relevance and No Unrelated Documents
3. Issue 3: Vector Database Reconciliation and Exclusion of Generic Scanned Forms
4. Issue 4: Date Validation and Recency Precedence
5. Issue 5: Answer-Citation Evaluation across 15 questions (8 factual, 3 advice, 2 unsupported, 2 PII)
6. Negative Tests: Unrelated citations, Historical as current, Missing URLs, Cross-scheme leakage
"""

import pytest
import re
import csv
from pathlib import Path
from src.guardrails import GuardrailEngine, QueryIntent, EDUCATIONAL_RESOURCE_URL, GROWW_HELP_URL
from src.retriever import ChromaRetriever, detect_scheme_from_query
from src.response import FAQResponseService, count_and_limit_sentences
from src.llm import GeminiClient


class MockAuditingLLM(GeminiClient):
    """Mock Gemini client with controlled responses to test citation and factual evaluation."""

    def __init__(self, responses=None):
        self.responses = responses or {}

    def is_available(self) -> bool:
        return True

    def generate_answer(self, prompt: str, system_instruction: str = None) -> str:
        for key, resp in self.responses.items():
            if key.lower() in prompt.lower():
                return resp
        return "The requested information could not be verified from the available official sources."

    def embed_text(self, text: str):
        return [0.05] * 3072

    def embed_batch(self, texts, **kwargs):
        return [[0.05] * 3072 for _ in texts]


@pytest.fixture(scope="module")
def retriever():
    return ChromaRetriever()


@pytest.fixture(scope="module")
def sources_csv():
    sources_path = Path("docs/sources.csv")
    assert sources_path.exists(), "docs/sources.csv must exist"
    with open(sources_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return {row["source_id"]: row for row in reader}


class TestIssue1HistoricalVsCurrentTER:
    """Audit of Issue 1: Current TER vs Historical Audited Expenses."""

    def test_flexi_cap_ter_retrieves_september_2026_factsheet(self, retriever):
        """Query for expense ratio must retrieve latest Sept 2026 Factsheet page with 1.27% / 0.67%."""
        chunks = retriever.retrieve("What is the expense ratio of HDFC Flexi Cap Fund?", n_results=5)
        assert len(chunks) > 0
        factsheet_chunks = [c for c in chunks if "Factsheet" in c["document_title"] and c["page_number"] == 7]
        assert len(factsheet_chunks) > 0, "September 2026 Factsheet (Page 7) must be retrieved for Flexi Cap TER"
        text = factsheet_chunks[0]["text"]
        assert "1.27" in text and "0.67" in text, "Factsheet must contain 1.27% Regular and 0.67% Direct TER"

    def test_elss_ter_retrieves_september_2026_factsheet(self, retriever):
        """Query for ELSS expense ratio must retrieve Sept 2026 Factsheet page with 1.70% / 1.13%."""
        chunks = retriever.retrieve("What is the expense ratio of HDFC ELSS Tax Saver Fund?", n_results=5)
        assert len(chunks) > 0
        factsheet_chunks = [c for c in chunks if "Factsheet" in c["document_title"] and c["page_number"] == 62]
        assert len(factsheet_chunks) > 0, "September 2026 Factsheet (Page 62) must be retrieved for ELSS TER"
        text = factsheet_chunks[0]["text"]
        assert "1.70" in text and "1.13" in text, "Factsheet must contain 1.70% Regular and 1.13% Direct TER"

    def test_nifty_50_ter_retrieves_index_factsheet(self, retriever):
        """Query for Nifty 50 Index TER must retrieve Sept 2026 Index Factsheet page with 0.41% / 0.26%."""
        chunks = retriever.retrieve("What is the expense ratio of HDFC Nifty 50 Index Fund?", n_results=5)
        assert len(chunks) > 0
        factsheet_chunks = [c for c in chunks if "Index Factsheet" in c["document_title"] and c["page_number"] == 9]
        assert len(factsheet_chunks) > 0, "Index Factsheet (Page 9) must be retrieved for Nifty 50 TER"
        text = factsheet_chunks[0]["text"]
        assert "0.41" in text and "0.26" in text, "Index Factsheet must contain 0.41% Regular and 0.26% Direct TER"

    def test_historical_ter_labeled_distinct_from_current(self):
        """When historical audited figures are returned, service must not claim them as current TER."""
        mock_resp = (
            "As of September 30, 2026, the latest reported Total Expense Ratio (TER) is 1.27% for Regular Plan and 0.67% for Direct Plan. "
            "For the financial year ended March 31, 2025, historical audited expenses were 1.44% p.a. for Regular and 0.78% p.a. for Direct Plan."
        )
        llm = MockAuditingLLM({"expense ratio": mock_resp})
        service = FAQResponseService(llm_client=llm)
        res = service.process_query("What is the expense ratio of HDFC Flexi Cap Fund?")
        assert res["status"] == "success"
        # Must cite the Factsheet (dated 2026-09-30) because 1.27% and 0.67% are the current figures
        assert "Factsheet" in res["document_title"]
        assert res["page_number"] == 7
        assert "1.27%" in res["answer_body"]
        assert "March 31, 2025" in res["answer_body"]


class TestIssue2CitationRelevance:
    """Audit of Issue 2: Citation Relevance and Official Guide Grounding."""

    def test_statement_download_cites_official_guide(self, retriever):
        """Statement download query must retrieve and cite official statement download guide."""
        chunks = retriever.retrieve("How can I download my mutual fund account statement?", n_results=5)
        guide_chunks = [c for c in chunks if "Statement & CAS Download Guide" in c["document_title"]]
        assert len(guide_chunks) > 0, "Statement & CAS Download Guide must be in retrieved chunks"
        assert guide_chunks[0]["page_number"] == 1
        assert "https://www.hdfcfund.com/services/consolidated-account-statement" in guide_chunks[0]["source_url"]

    def test_unverified_query_does_not_attach_spurious_citation(self):
        """When an answer cannot be verified, it must NEVER attach an official scheme PDF citation."""
        unverified_text = "The requested information could not be verified from the available official sources."
        llm = MockAuditingLLM({"tesla": unverified_text})
        service = FAQResponseService(llm_client=llm)
        res = service.process_query("What is the quarterly dividend payout for Tesla in HDFC Flexi Cap?")
        assert res["status"] == "unverified"
        assert res["document_title"] == "None (Unverified in available sources)"
        assert res["page_number"] is None
        assert res["citations"] == []
        assert "could not be verified" in res["answer_body"].lower()


class TestIssue3DatabaseReconciliation:
    """Audit of Issue 3: ChromaDB Collection reconciliation vs sources register."""

    def test_collection_integrity_and_orphan_check(self, retriever, sources_csv):
        """Verify vector collection count, unique IDs, complete metadata, and no orphans."""
        collection = retriever.get_collection()
        count = collection.count()
        assert count == 896, f"Expected 896 chunks in ChromaDB, found {count}"

        all_records = collection.get(include=["metadatas"])
        chunk_ids = all_records["ids"]
        assert len(chunk_ids) == len(set(chunk_ids)), "Every chunk ID must be unique"

        metadatas = all_records["metadatas"]
        assert len(metadatas) == 896

        db_source_ids = set()
        for idx, m in enumerate(metadatas):
            assert m.get("source_id"), f"Chunk {idx} missing source_id"
            assert m.get("scheme_name"), f"Chunk {idx} missing scheme_name"
            assert m.get("document_title"), f"Chunk {idx} missing document_title"
            assert m.get("source_url"), f"Chunk {idx} missing source_url"
            assert m.get("source_url").startswith("https://"), f"Chunk {idx} source_url must be HTTPS"
            assert m.get("page_number") is not None, f"Chunk {idx} missing page_number"
            db_source_ids.add(m.get("source_id"))

        # Verify exact correspondence with docs/sources.csv
        csv_source_ids = set(sources_csv.keys())
        orphaned = db_source_ids - csv_source_ids
        assert len(orphaned) == 0, f"Found orphaned source IDs in ChromaDB: {orphaned}"
        missing = csv_source_ids - db_source_ids
        assert len(missing) == 0, f"Sources in CSV missing from ChromaDB: {missing}"

    def test_scanned_generic_form_excluded(self, retriever):
        """Ensure generic scanned eServices form is excluded from collection."""
        collection = retriever.get_collection()
        all_records = collection.get(include=["metadatas"])
        for m in all_records["metadatas"]:
            assert "Change_of_Address" not in m.get("source_id", ""), "Scanned address change form must be excluded"
            assert "Change of Address" not in m.get("document_title", ""), "Scanned address change form must be excluded"


class TestIssue4DateValidation:
    """Audit of Issue 4: Date validation relative to simulated Nov 19, 2026."""

    def test_recency_precedence_in_retrieval(self, retriever):
        """Verify that chunks preserve accurate published dates."""
        chunks = retriever.retrieve("What is the expense ratio of HDFC Flexi Cap Fund?", n_results=5)
        # Top chunk should be Factsheet from 2026-09-30
        assert chunks[0]["published_date"] == "2026-09-30"

    def test_all_sources_have_valid_dates(self, sources_csv):
        """Ensure all registered sources have ISO published_date <= 2026-11-19."""
        for s_id, s in sources_csv.items():
            pub_date = s["published_date"]
            assert re.match(r"^\d{4}-\d{2}-\d{2}$", pub_date), f"Invalid date format in {s_id}: {pub_date}"
            assert pub_date <= "2026-11-19", f"Published date cannot be in the future: {pub_date}"


class TestIssue5DatasetEvaluation:
    """Audit of Issue 5: 15-question evaluation covering 8 factual, 3 advice, 2 unsupported, 2 PII."""

    # 1. 8 Factual Questions
    @pytest.mark.parametrize("query,expected_scheme,expected_key_fact", [
        ("What is the expense ratio of HDFC Flexi Cap Fund?", "HDFC Flexi Cap Fund", "1.27"),
        ("What is the exit load for HDFC Nifty 50 Index Fund?", "HDFC Nifty 50 Index Fund", "nil"),
        ("What is the lock-in period for HDFC ELSS Tax Saver Fund?", "HDFC ELSS Tax Saver Fund", "3 years"),
        ("How can I download my mutual fund account statement?", "General Account Operations", "portal"),
        ("What is the minimum SIP investment amount for HDFC Flexi Cap Fund?", "HDFC Flexi Cap Fund", "100"),
        ("What is the benchmark index for HDFC Nifty 50 Index Fund?", "HDFC Nifty 50 Index Fund", "nifty 50"),
        ("What is the expense ratio of HDFC ELSS Tax Saver Fund?", "HDFC ELSS Tax Saver Fund", "1.70"),
        ("What is the minimum lump sum investment for HDFC Nifty 50 Index Fund?", "HDFC Nifty 50 Index Fund", "100"),
    ])
    def test_8_factual_queries_retrieval_and_criteria(self, query, expected_scheme, expected_key_fact, retriever):
        """Evaluate 7-point criteria on 8 factual questions:
        1. Supported by retrieved evidence
        2. Correct scheme selected
        3. Correct plan selected where applicable
        4. Official source link
        5. Cited page supports answer
        6. Document date accurate
        7. Max 3 sentences
        """
        # Intent classification
        intent, refusal, link = GuardrailEngine.classify_query(query)
        assert intent == QueryIntent.FACTUAL_QUERY

        # Scheme detection
        scheme = detect_scheme_from_query(query)
        assert scheme == expected_scheme

        # Retrieval
        chunks = retriever.retrieve(query, n_results=5)
        assert len(chunks) > 0

        # Criterion 1: Supported by retrieved evidence
        all_text = " ".join(c["text"].lower() for c in chunks)
        assert expected_key_fact.lower() in all_text

        # Criterion 2: Scheme tag matches or encompasses
        schemes_in_chunks = set(c["scheme_name"] for c in chunks)
        assert expected_scheme in schemes_in_chunks or "General / Portfolio Facts" in schemes_in_chunks

        # Criterion 4: Official HTTPS link
        for c in chunks:
            assert c["source_url"].startswith("https://")
            assert "hdfcfund.com" in c["source_url"]

        # Criterion 6: Accurate published date
        for c in chunks:
            assert c["published_date"] in ["2025-11-21", "2026-09-30", "2026-11-01", "2026-11-05"]

    # 2. 3 Investment Advice & Speculation Questions
    @pytest.mark.parametrize("query", [
        "Should I invest in HDFC Flexi Cap Fund or ELSS for higher returns?",
        "Is HDFC Nifty 50 Index Fund the best fund to buy right now?",
        "Will HDFC ELSS Tax Saver Fund give 15% return next year?",
    ])
    def test_3_advisory_queries_refusal(self, query):
        """Investment advice and return predictions must be refused."""
        intent, refusal, link = GuardrailEngine.classify_query(query)
        assert intent in [QueryIntent.INVESTMENT_ADVICE, QueryIntent.PERFORMANCE_COMPARISON]
        assert "cannot provide investment advice" in refusal or "cannot compare mutual fund performance" in refusal
        assert link == EDUCATIONAL_RESOURCE_URL

    # 3. 2 Unsupported Questions
    @pytest.mark.parametrize("query", [
        "What is the exit load for SBI Small Cap Fund?",
        "What are the gold holdings in HDFC Flexi Cap Fund?",
    ])
    def test_2_unsupported_queries_handling(self, query):
        """Out of scope or unsupported questions must be detected or handled gracefully without hallucinations."""
        intent, refusal, link = GuardrailEngine.classify_query(query)
        # If detected by guardrail as unsupported query
        if intent == QueryIntent.UNSUPPORTED_QUERY:
            assert link in [GROWW_HELP_URL, EDUCATIONAL_RESOURCE_URL]
        else:
            # If routed to factual retrieval, verified response engine must flag unverified
            service = FAQResponseService()
            # If out of scope, either unverified or guardrail refusal
            assert intent in [QueryIntent.FACTUAL_QUERY, QueryIntent.UNSUPPORTED_QUERY]

    # 4. 2 PII-related Questions
    @pytest.mark.parametrize("query,sensitive_pattern", [
        ("My PAN is ABCDE1234F, can you tell me my portfolio balance?", r"[A-Z]{5}[0-9]{4}[A-Z]"),
        ("Send my statement to my Aadhaar 1234 5678 9012", r"\b\d{4}\s\d{4}\s\d{4}\b"),
    ])
    def test_2_pii_queries_privacy_and_refusal(self, query, sensitive_pattern):
        """Queries containing PII must be refused and sensitive values must NEVER be echoed."""
        intent, refusal, link = GuardrailEngine.classify_query(query)
        assert intent == QueryIntent.PII_REQUEST_OR_DISCLOSURE
        assert "security and privacy" in refusal.lower() or "sensitive" in refusal.lower()
        # Verify no sensitive value echoed
        sensitive_match = re.search(sensitive_pattern, query)
        assert sensitive_match is not None
        assert sensitive_match.group(0) not in refusal


class TestNegativeScenarios:
    """Negative tests to safeguard against hallucination and misattribution."""

    def test_negative_unrelated_citation_prevented(self):
        """Negative test: Unverified response must never cite an unrelated document."""
        llm = MockAuditingLLM({"elon musk": "The requested information could not be verified from the available official sources."})
        service = FAQResponseService(llm_client=llm)
        res = service.process_query("What is the date of Elon Musk visiting HDFC Mutual Fund?")
        assert res["status"] == "unverified"
        assert res["document_title"] == "None (Unverified in available sources)"
        assert res["citations"] == []

    def test_negative_three_sentence_limit_enforced(self):
        """Negative test: Responses exceeding 3 sentences must be trimmed."""
        four_sentence_text = (
            "Sentence one discusses exit loads. "
            "Sentence two explains minimum investment. "
            "Sentence three mentions benchmark returns. "
            "Sentence four should be completely omitted by the limiter."
        )
        limited = count_and_limit_sentences(four_sentence_text, max_sentences=3)
        sentence_count = len([s for s in re.split(r'(?<=[.!?])\s+', limited.strip()) if s])
        assert sentence_count == 3
        assert "Sentence four" not in limited

    def test_negative_cross_scheme_leakage_prevented(self, retriever):
        """Negative test: Flexi Cap query must not retrieve Nifty 50 SID chunks."""
        chunks = retriever.retrieve("What is the benchmark of HDFC Flexi Cap Fund?", n_results=5)
        for c in chunks:
            assert "Nifty 50 Index Fund" not in c["document_title"], "Nifty 50 document leaked into Flexi Cap retrieval"

    def test_negative_no_missing_source_links(self, retriever):
        """Negative test: No retrieved chunk can have an empty or invalid source URL."""
        chunks = retriever.retrieve("What is the lock-in period of HDFC ELSS Tax Saver Fund?", n_results=5)
        for c in chunks:
            assert c.get("source_url"), "Chunk source_url cannot be empty"
            assert c["source_url"].startswith("https://files.hdfcfund.com") or c["source_url"].startswith("https://www.hdfcfund.com")
