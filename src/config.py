"""
Configuration module for the Groww Mutual Fund FAQ Assistant.
Handles environment variables, filesystem paths, and application constants.
"""

from pathlib import Path
import os
from typing import List, Dict, Any
from dotenv import load_dotenv

# Load environment variables from .env if present
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(dotenv_path=BASE_DIR / ".env")


class AppConfig:
    """Application configuration and brand styling constants."""

    # Project metadata
    APP_NAME: str = "Groww Mutual Fund FAQ Assistant"
    PRODUCT_CONTEXT: str = "Groww - HDFC Mutual Fund FAQ Assistant"
    DISCLAIMER_TEXT: str = "Facts-only. No investment advice."
    WELCOME_HEADING: str = "Your Mutual Fund Questions, Answered."
    WELCOME_SUBHEADING: str = (
        "Ask factual questions about supported HDFC Mutual Fund schemes. "
        "All answers are grounded strictly in official scheme documents (SID/KIM)."
    )

    # Groww Design System Color Tokens
    COLOR_PRIMARY: str = "#00D09C"          # Groww Emerald Green
    COLOR_PRIMARY_HOVER: str = "#00B887"
    COLOR_BG_PRIMARY: str = "#FFFFFF"       # Clean White
    COLOR_BG_SECONDARY: str = "#F9FAFB"     # Soft Gray background
    COLOR_TEXT_MAIN: str = "#1F2228"        # Dark slate typography
    COLOR_TEXT_MUTED: str = "#6B7280"       # Muted gray text
    COLOR_BORDER: str = "#E5E7EB"           # Light border
    COLOR_ACCENT_LIGHT: str = "#E6FBF5"     # Very light green tint

    # Supported Schemes for Milestone 1
    SUPPORTED_SCHEMES: List[str] = [
        "HDFC Nifty 50 Index Fund",
        "HDFC Flexi Cap Fund",
        "HDFC ELSS Tax Saver Fund",
    ]

    # Pre-defined Example Questions
    EXAMPLE_QUESTIONS: List[str] = [
        "What is the expense ratio of HDFC Flexi Cap Fund?",
        "What is the lock-in period of HDFC ELSS Tax Saver Fund?",
        "How can I download my mutual fund account statement?",
    ]

    # Paths & ChromaDB Configuration
    BASE_DIR: Path = BASE_DIR
    DATA_DIR: Path = BASE_DIR / "data"
    RAW_DATA_DIR: Path = BASE_DIR / "data" / "raw"
    PROCESSED_DATA_DIR: Path = BASE_DIR / "data" / "processed"
    CHROMA_PERSIST_DIR: Path = Path(os.getenv("CHROMA_PERSIST_DIR", str(BASE_DIR / "data" / "chroma_db")))
    CHROMA_COLLECTION_NAME: str = "hdfc_mutual_fund_knowledge"
    DOCS_DIR: Path = BASE_DIR / "docs"
    SOURCES_CSV_PATH: Path = BASE_DIR / "docs" / "sources.csv"

    # Database Configuration (Neon PostgreSQL & pgvector)
    DATABASE_URL: str = os.getenv("DATABASE_URL", "")
    VECTOR_BACKEND: str = os.getenv("VECTOR_BACKEND", "neon")

    # API Configuration
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    LLM_MODEL: str = os.getenv("LLM_MODEL", "gemini-3.5-flash-lite")
    EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "gemini-embedding-001")
    APP_ENV: str = os.getenv("APP_ENV", "development")
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

    @classmethod
    def is_api_key_configured(cls) -> bool:
        """Check if Gemini API key is provided and non-empty."""
        return bool(cls.GEMINI_API_KEY and cls.GEMINI_API_KEY.strip() != "your_gemini_api_key_here")

    @classmethod
    def is_db_configured(cls) -> bool:
        """Check if Neon PostgreSQL database connection string is provided."""
        return bool(cls.DATABASE_URL and cls.DATABASE_URL.strip().startswith("postgres"))

    @classmethod
    def get_safe_db_url(cls) -> str:
        """Return masked database connection string for logs/diagnostics."""
        if not cls.DATABASE_URL:
            return "Not Configured"
        import re
        # Mask password in postgresql://user:password@host/db
        return re.sub(r":([^@]+)@", ":****@", cls.DATABASE_URL)

    @classmethod
    def get_status_summary(cls) -> Dict[str, Any]:
        """Return safe configuration status without exposing sensitive secrets."""
        return {
            "app_name": cls.APP_NAME,
            "environment": cls.APP_ENV,
            "api_key_configured": cls.is_api_key_configured(),
            "database_configured": cls.is_db_configured(),
            "vector_backend": cls.VECTOR_BACKEND,
            "chroma_dir_exists": cls.CHROMA_PERSIST_DIR.exists(),
            "supported_schemes_count": len(cls.SUPPORTED_SCHEMES),
        }


# Singleton config instance
config = AppConfig()
