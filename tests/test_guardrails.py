"""
Unit tests for query guardrails.
Verifies compliance boundary between factual scheme questions and prohibited advisory requests.
"""

import pytest
from src.guardrails import GuardrailEngine, QueryIntent


class TestGuardrails:
    """Test suite for intent classification and advisory detection."""

    @pytest.mark.parametrize("query", [
        "What is the expense ratio of HDFC Flexi Cap Fund?",
        "What is the lock-in period of HDFC ELSS Tax Saver Fund?",
        "How can I download my mutual fund account statement?",
        "What is the benchmark of HDFC Nifty 50 Index Fund?",
        "What is the exit load for HDFC Flexi Cap Fund?",
    ])
    def test_factual_questions_are_allowed(self, query: str):
        intent, refusal, *link = GuardrailEngine.classify_query(query)
        assert intent == QueryIntent.FACTUAL_QUERY
        assert refusal == ""
        assert GuardrailEngine.is_safe_for_retrieval(query) is True

    @pytest.mark.parametrize("query", [
        "Should I invest in HDFC Flexi Cap Fund?",
        "Which fund is better between HDFC Flexi Cap and Nifty 50?",
        "Which scheme is best for high returns?",
        "Where should I invest 50000 rupees?",
        "Give me advice on whether to buy HDFC ELSS fund now",
    ])
    def test_investment_advice_is_blocked(self, query: str):
        intent, refusal, *link = GuardrailEngine.classify_query(query)
        assert intent == QueryIntent.INVESTMENT_ADVICE
        assert "cannot provide investment advice" in refusal
        assert GuardrailEngine.is_safe_for_retrieval(query) is False

    @pytest.mark.parametrize("query", [
        "Will HDFC Nifty 50 double my money in 3 years?",
        "What is the guaranteed return of HDFC ELSS Tax Saver?",
        "Will it beat the market next year?",
    ])
    def test_return_speculation_is_blocked(self, query: str):
        intent, refusal, *link = GuardrailEngine.classify_query(query)
        assert intent in [QueryIntent.RETURN_SPECULATION, QueryIntent.PERFORMANCE_COMPARISON]
        assert "cannot compare mutual fund performance" in refusal or "cannot provide investment advice" in refusal
        assert GuardrailEngine.is_safe_for_retrieval(query) is False

    def test_empty_query(self):
        intent, refusal, *link = GuardrailEngine.classify_query("")
        assert intent in [QueryIntent.OUT_OF_SCOPE, QueryIntent.UNSUPPORTED_QUERY]
        assert "Please enter a" in refusal
