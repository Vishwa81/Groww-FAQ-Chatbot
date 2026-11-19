"""
Guardrails module for Groww Mutual Fund FAQ Assistant.
Classifies incoming questions into compliance categories, enforces non-advisory policies,
detects and redacts sensitive PII, and provides polite educational refusal responses.
"""

from enum import Enum
from typing import Tuple, List, Optional
import re

EDUCATIONAL_RESOURCE_URL = "https://www.amfiindia.com/investor-corner/knowledge-center"
GROWW_HELP_URL = "https://groww.in/help"


class QueryIntent(str, Enum):
    """Categorization of incoming user queries."""
    FACTUAL_QUERY = "FACTUAL_QUERY"
    INVESTMENT_ADVICE = "INVESTMENT_ADVICE"
    PERFORMANCE_COMPARISON = "PERFORMANCE_COMPARISON"
    UNSUPPORTED_QUERY = "UNSUPPORTED_QUERY"
    PII_REQUEST_OR_DISCLOSURE = "PII_REQUEST_OR_DISCLOSURE"

    # Backward compatibility aliases
    RETURN_SPECULATION = "PERFORMANCE_COMPARISON"
    OUT_OF_SCOPE = "UNSUPPORTED_QUERY"


class GuardrailEngine:
    """Evaluates user queries against compliance, privacy, and scope rules."""

    # PII Regex Patterns
    PAN_PATTERN = r"\b[A-Za-z]{5}[0-9]{4}[A-Za-z]\b"
    AADHAAR_PATTERN = r"\b(?:\d{4}\s\d{4}\s\d{4}|\d{12})\b"
    PHONE_PATTERN = r"\b(?:\+91[\-\s]?)?[6-9]\d{9}\b"
    EMAIL_PATTERN = r"\b[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+\b"
    BANK_ACCOUNT_PATTERN = r"(?i)\b(?:account|ac|acc|folio|bank|a\/c)\s*(?:no\.?|num|number)?\s*[:\-#]?\s*(\d{9,18})\b"
    OTP_PIN_PATTERN = r"(?i)\b(?:otp|pin|password|cvv|secret)\s*(?:is|:|-)?\s*([0-9]{4,8})\b"

    # Keywords signaling investment advice or recommendations
    ADVISORY_PATTERNS: List[str] = [
        r"\bshould i (invest|buy|sell|switch|redeem|hold)\b",
        r"\bwhich (?:mutual )?(?:fund|scheme) is (?:better|best|recommended|good)\b",
        r"\bwhich (?:mutual )?(?:fund|scheme) will generate (?:higher|better|more) returns?\b",
        r"\bwhere should i invest\b",
        r"\bis (?:it|this) a good (?:time|fund|investment)\b",
        r"\bis .*the best fund\b",
        r"\b(?:the )?best fund to (?:buy|invest|choose)\b",
        r"\bhelp me choose\b",
        r"\bgive me (?:advice|recommendation|portfolio tips)\b",
        r"\bwhich one should i choose\b",
        r"\bcan you suggest (?:a|the best) (?:fund|portfolio)\b",
        r"\bportfolio (?:recommendation|allocation)\b",
        r"\bhow should i allocate\b",
    ]

    # Keywords signaling performance comparisons or return speculation
    COMPARISON_PATTERNS: List[str] = [
        r"\bcompare (?:the )?(?:returns|performance)\b",
        r"\bwhich (?:one|fund|scheme) will (?:give|have) (?:higher|more|better) returns?\b",
        r"\bwhich (?:one|fund|scheme) (?:gives?|generated) (?:higher|more|better) returns?\b",
        r"\b(?:will .*\bbeat|beats?) the market\b",
        r"\bwill .*double (?:my )?money\b",
        r"\bwill .* (?:give|generate|deliver|provide) .*(?:%|returns?|profit)\b",
        r"\bguaranteed return\b",
        r"\bexpected returns?\b",
        r"\bpredict (?:the )?nav\b",
        r"\bfuture returns?\b",
        r"\bwho (?:performed|performs) better\b",
        r"\bwhich fund has better returns\b",
    ]

    # Keywords related to supported schemes and operational FAQ
    SUPPORTED_KEYWORDS: List[str] = [
        "nifty 50",
        "flexi cap",
        "elss",
        "tax saver",
        "hdfc",
        "expense ratio",
        "lock-in",
        "lock in",
        "nav",
        "exit load",
        "minimum sip",
        "sip",
        "lumpsum",
        "statement",
        "cas",
        "download",
        "account statement",
        "benchmark",
        "portfolio",
        "fund manager",
        "folio",
        "aum",
        "turnover",
        "risk",
        "riskometer",
        "dividend",
        "idcw",
        "allotment",
        "cutoff",
        "cut-off",
        "stamp duty",
        "transaction",
    ]

    # Explicit competitors or out-of-scope AMC mentions
    OUT_OF_SCOPE_AMCS: List[str] = [
        "sbi", "icici", "axis", "kotak", "nippon", "mirae", "tata", "uti", "dsp", "parag parikh"
    ]

    @classmethod
    def redact_pii(cls, text: str) -> str:
        """Sanitize text by redacting sensitive identifiers to prevent echoing in logs/messages."""
        # Redact account and OTP with contextual keywords FIRST
        sanitized = re.sub(
            cls.BANK_ACCOUNT_PATTERN,
            lambda m: m.group(0).replace(m.group(1), "[REDACTED_ACCOUNT]"),
            text
        )
        sanitized = re.sub(
            cls.OTP_PIN_PATTERN,
            lambda m: m.group(0).replace(m.group(1), "[REDACTED_OTP]"),
            sanitized
        )
        sanitized = re.sub(cls.PAN_PATTERN, "[REDACTED_PAN]", sanitized)
        sanitized = re.sub(cls.AADHAAR_PATTERN, "[REDACTED_AADHAAR]", sanitized)
        sanitized = re.sub(cls.EMAIL_PATTERN, "[REDACTED_EMAIL]", sanitized)
        sanitized = re.sub(cls.PHONE_PATTERN, "[REDACTED_PHONE]", sanitized)
        return sanitized

    @classmethod
    def detect_pii(cls, text: str) -> bool:
        """Detect whether text contains likely sensitive personal or financial identifiers."""
        if re.search(cls.PAN_PATTERN, text):
            return True
        if re.search(cls.AADHAAR_PATTERN, text):
            return True
        if re.search(cls.EMAIL_PATTERN, text):
            return True
        if re.search(cls.PHONE_PATTERN, text):
            return True
        if re.search(cls.BANK_ACCOUNT_PATTERN, text):
            return True
        if re.search(cls.OTP_PIN_PATTERN, text):
            return True
        return False

    @classmethod
    def classify_query(cls, query: str) -> Tuple[QueryIntent, str, Optional[str]]:
        """
        Classify incoming query into compliance categories.
        Returns: (QueryIntent, refusal_message, official_educational_link)
        """
        cleaned = query.strip()
        cleaned_lower = cleaned.lower()

        if not cleaned:
            return (
                QueryIntent.UNSUPPORTED_QUERY,
                "Please enter a factual question about supported HDFC Mutual Fund schemes.",
                GROWW_HELP_URL,
            )

        # 1. PII Check: Stop processing immediately if sensitive personal data is present
        if cls.detect_pii(cleaned):
            return (
                QueryIntent.PII_REQUEST_OR_DISCLOSURE,
                "For your security and privacy, this assistant does not collect, process, or store personal identifiers, account numbers, or OTPs. Please do not share sensitive financial information. For account-specific inquiries, please visit the Groww Help Center.",
                GROWW_HELP_URL,
            )

        # 2. Performance Comparison Check
        for pattern in cls.COMPARISON_PATTERNS:
            if re.search(pattern, cleaned_lower):
                return (
                    QueryIntent.PERFORMANCE_COMPARISON,
                    "I am a facts-only assistant and cannot compare mutual fund performance, rank schemes for purchase decisions, or predict future returns. Mutual fund investments are subject to market risks. Please consult official educational resources to understand fund selection.",
                    EDUCATIONAL_RESOURCE_URL,
                )

        # 3. Investment Advice Check
        for pattern in cls.ADVISORY_PATTERNS:
            if re.search(pattern, cleaned_lower):
                return (
                    QueryIntent.INVESTMENT_ADVICE,
                    "I cannot provide investment advice, buy/sell recommendations, or portfolio allocations. As a facts-only tool, I only provide verified details directly from official scheme documents. Please consult a SEBI-registered Investment Adviser for investment recommendations.",
                    EDUCATIONAL_RESOURCE_URL,
                )

        # 4. Out-of-Scope AMC Check
        words = cleaned_lower.split()
        for amc in cls.OUT_OF_SCOPE_AMCS:
            if re.search(rf"\b{re.escape(amc)}\b", cleaned_lower) and "hdfc" not in cleaned_lower:
                return (
                    QueryIntent.UNSUPPORTED_QUERY,
                    f"This assistant is currently limited to official HDFC Mutual Fund schemes and general account procedures. Queries regarding other fund houses like {amc.upper()} are currently outside our scope.",
                    EDUCATIONAL_RESOURCE_URL,
                )

        # 5. General Scope Relevance Check
        is_relevant = any(kw in cleaned_lower for kw in cls.SUPPORTED_KEYWORDS)
        if not is_relevant and len(words) > 3:
            return (
                QueryIntent.UNSUPPORTED_QUERY,
                "This question appears outside our supported scope. I can answer factual questions regarding HDFC Nifty 50 Index Fund, HDFC Flexi Cap Fund, HDFC ELSS Tax Saver Fund, and mutual fund account statement downloads.",
                GROWW_HELP_URL,
            )

        return (QueryIntent.FACTUAL_QUERY, "", None)

    @classmethod
    def is_safe_for_retrieval(cls, query: str) -> bool:
        """Returns True if query passes all guardrails and should proceed to RAG retrieval."""
        intent, _, _ = cls.classify_query(query)
        return intent == QueryIntent.FACTUAL_QUERY
