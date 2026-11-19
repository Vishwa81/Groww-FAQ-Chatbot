# Groww Mutual Fund FAQ Assistant

> **Product Management Fellowship Milestone — Production-Grade RAG Engine**  
> *"Facts-only. No investment advice."*

A clean, modern, factual conversational assistant inspired by **Groww's** user experience. The assistant answers factual queries regarding select mutual fund schemes using official documents (Scheme Information Documents [SID] and Key Information Memorandums [KIM]).

---

## 🎯 Product Context & Scope

- **Product**: Groww Inspired Experience
- **Asset Management Company (AMC)**: HDFC Mutual Fund
- **Initial Supported Schemes**:
  1. **HDFC Nifty 50 Index Fund** (Large Cap Index)
  2. **HDFC Flexi Cap Fund** (Active Diversified Equity)
  3. **HDFC ELSS Tax Saver Fund** (Tax Saving Equity, 3-Year Lock-in)
  4. **General Account Operations** (Consolidated Account Statements & Service Forms)
- **Primary Use Case**: Retrieve strictly verified factual parameters (such as expense ratios, exit loads, lock-in terms, benchmark indices, fund managers, and operational account procedures like statement downloads).
- **Core Guardrail**: **NOT an investment advisory tool**. Any request for recommendations, returns forecasts, asset allocation, or "which fund should I buy" is strictly refused by compliance guardrails.

---

## 🛠️ Tech Stack

| Component | Technology | Purpose |
| :--- | :--- | :--- |
| **Frontend** | Streamlit | Clean, modern UI inspired by Groww's design system |
| **LLM Generation** | Google Gemini API (`gemini-3.5-flash-lite`) | Grounded answer generation, strict 3-sentence constraint |
| **Embeddings** | Gemini Embeddings (`gemini-embedding-001`) | 3072-dimensional vector representation of text chunks |
| **Vector Database (Cloud)** | Neon PostgreSQL + `pgvector` | Scalable cloud vector store with `halfvec(3072)` HNSW indexing |
| **Vector Database (Local)** | ChromaDB (`hdfc_mutual_fund_knowledge`) | Persistent local fallback store with 896 indexed chunks |
| **PDF Extraction** | PyMuPDF (`pymupdf`) | High-fidelity text and table extraction from SIDs/KIMs |
| **Configuration** | `python-dotenv` | Secure environment variable management |
| **Testing** | `pytest` | 90 comprehensive tests covering guardrails, PII, accuracy audit, Neon & RAG |

---

## 📂 Project Structure

```text
groww-mutual-fund-FAQ-assistant/
│
├── app.py                                  # Main Streamlit web application with live RAG
├── requirements.txt                        # Python dependencies (includes psycopg & pgvector)
├── .env.example                            # Sample environment configuration template
├── .env                                    # Local environment configuration (Git-ignored)
├── .gitignore                              # Git ignore rules (protects API keys and local data)
├── README.md                               # Project documentation and setup guide
│
├── .streamlit/
│   └── config.toml                         # Headless server & telemetry settings
│
├── src/                                    # Core backend modules
│   ├── config.py                           # Settings, color tokens, and paths
│   ├── llm.py                              # Gemini API client (generation + gemini-embedding-001)
│   ├── neon_retriever.py                   # Neon PostgreSQL pgvector retriever with HNSW & keyword fallback
│   ├── retriever.py                        # ChromaDB vector store retriever & scheme filter
│   ├── ingestion.py                        # PyMuPDF extractor, chunker & source catalog
│   ├── guardrails.py                       # Intent classification, PII redaction, advisory prevention
│   ├── prompts.py                          # Grounded system prompt & untrusted data boundaries
│   └── response.py                         # RAG response orchestration & citation engine
│
├── data/                                   # Data storage directory
│   ├── raw/                                # 10 official PDFs (SIDs, KIMs, Factsheets, Guides)
│   ├── processed/                          # Processed document data
│   └── chroma_db/                          # ChromaDB persistent vector database (896 vectors)
│
├── docs/                                   # Project documentation & compliance
│   ├── sources.csv                         # Official document tracking register & URLs (10 sources)
│   ├── neon_migration_report.md            # Detailed Neon PostgreSQL & pgvector migration report
│   ├── accuracy_audit.md                   # Strict factual accuracy & citation audit report
│   ├── sample_qa.md                        # In-scope factual vs advisory query specs
│   └── architecture.md                     # End-to-end system and verification flow
│
├── scripts/                                # Administrative & ingestion utilities
│   ├── ingest_documents.py                 # PDF extraction, chunking, and ChromaDB indexing
│   └── migrate_chroma_to_neon.py           # Idempotent batch migration from ChromaDB to Neon
│
└── tests/                                  # Production test suite (90 passing tests)
    ├── test_neon_retriever.py              # Neon database connectivity, pgvector, and search tests
    ├── test_accuracy_audit.py              # TER distinction, citation relevance, and recency tests
    ├── test_guardrails.py                  # PII, advisory refusal, and compliance tests
    ├── test_rag_engine.py                  # Integrated RAG generation and constraint tests
    ├── test_ingestion_and_retrieval.py     # Document processing and vector indexing tests
    └── test_retrieval.py                   # Retriever unit tests
│   └── disclaimer.md                       # Regulatory disclaimer ("Facts-only. No advice")
│
├── scripts/                                # Automation & operations scripts
│   ├── download_documents.py               # Downloads official HDFC PDFs from portals
│   └── ingest_documents.py                 # Ingestion & vector indexing pipeline runner
│
└── tests/                                  # Automated test suite (79 tests, 100% passing)
    ├── test_guardrails.py                  # Unit tests for query guardrails
    ├── test_retrieval.py                   # Tests for retriever initialization
    ├── test_ingestion_and_retrieval.py     # Tests for extraction, chunking, and persistence
    ├── test_rag_engine.py                  # Integration tests for RAG engine and PII protection
    └── test_accuracy_audit.py              # Strict factual accuracy, TER recency, and citation tests
```

---

## 🚀 Getting Started

### 1. Prerequisites
- Python 3.10 to 3.14 installed on your machine.
- Google Gemini API Key (obtain from [Google AI Studio](https://aistudio.google.com/)).

### 2. Virtual Environment Setup

**Windows (PowerShell):**
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

**macOS / Linux:**
```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Configure Environment Variables
Copy `.env.example` to `.env` and fill in your Gemini API key:
```bash
cp .env.example .env
```
Edit `.env`:
```ini
GEMINI_API_KEY=your_actual_gemini_api_key_here
APP_ENV=development
CHROMA_PERSIST_DIR=data/chroma_db
EMBEDDING_MODEL=gemini-embedding-001
LLM_MODEL=gemini-3.5-flash-lite
```

---

## 📥 Ingestion & Vector Indexing Pipeline

### 1. Download Official Documents
To fetch all official SIDs, KIMs, and forms from HDFC Mutual Fund portals:
```bash
python scripts/download_documents.py
```

### 2. Run Document Ingestion & Embedding
To extract text, generate overlapping chunks (~800 tokens, 120 tokens overlap), generate `gemini-embedding-001` embeddings, and store them into ChromaDB:
```bash
python -m scripts.ingest_documents
```

**Features of the Ingestion Pipeline:**
- **Duplicate Prevention & Idempotency**: Computes a SHA-256 hash of each PDF. If a document is already indexed and unchanged, re-embedding is skipped automatically to conserve API tokens.
- **Dynamic Rate-Limit Handling**: Automatically detects Google AI Studio 429 quota responses (`30,000 tokens/min`), reads the server's `retryDelay`, and pauses cleanly until the quota bucket refreshes.
- **Force Re-indexing**: To override cache and force complete re-indexing:
  ```bash
  python -m scripts.ingest_documents --force
  ```

---

## 🛡️ Guardrails & Compliance System

The assistant classifies every query into 5 compliance categories:
1. `FACTUAL_QUERY`: Passed to the RAG retrieval engine.
2. `INVESTMENT_ADVICE`: Strictly refused ("I cannot provide investment advice...").
3. `PERFORMANCE_COMPARISON`: Strictly refused ("I cannot compare mutual fund performance...").
4. `UNSUPPORTED_QUERY`: Polite out-of-scope redirection with help center links.
5. `PII_REQUEST_OR_DISCLOSURE`: Personal identifiers (PAN, Aadhaar, account numbers, OTPs, phone numbers, emails) are detected, rejected, and redacted—they are never stored or echoed back.

---

## 🧪 Testing & Accuracy Audit

Run the full automated test suite (79 tests across 5 modules):
```bash
python -m pytest tests/ -v
```

All 79 tests pass with 0 failures:
- Intent classification across 5 categories
- PII detection, redaction, and non-echoing
- 3-sentence answer length constraint
- Unindexed vector store error handling
- Zero fabricated citations and missing context verification
- Conflicting document dates sorting (latest monthly factsheet precedence)
- Historical audited expenses vs current Total Expense Ratio (TER) distinction
- Verified account statement download procedural grounding
- ChromaDB collection reconciliation (896 chunks, 10 registered sources, 0 duplicates, 0 orphans)
- Automatic and explicit scheme filtering
- ChromaDB persistence and idempotency

For detailed methodology, benchmark matrices, and audit findings, see [docs/accuracy_audit.md](file:///c:/Users/vishv/Downloads/NL%20building%20app%20With%20AI/groww-mutual-fund-FAQ-assistant/docs/accuracy_audit.md).

---

## 🖥️ Running the Application

Start the Streamlit application:
```bash
streamlit run app.py
```
Open your browser at `http://localhost:8501`.

---

## ⚡ Project Milestones

- [x] **Milestone 1: Clean Groww UI Foundation**: Modern Groww-inspired theme (`#00D09C`), typography, example questions, and compliance disclaimer.
- [x] **Milestone 2A: Official Document Acquisition**: Downloaded official SIDs, KIMs, monthly factsheets, and statement download guides directly from HDFC Mutual Fund portals into `data/raw/` and registered in `docs/sources.csv`.
- [x] **Milestone 2B: Ingestion & Vector Indexing**: Extracted 524 pages with PyMuPDF, chunked ~800 tokens with 120 token overlap, embedded with `gemini-embedding-001` (3072 dims), and persisted 896 vectors in ChromaDB collection `hdfc_mutual_fund_knowledge`.
- [x] **Milestone 3: Grounded RAG Question-Answering Engine**:
  - Semantic similarity search with scheme filtering and date precedence.
  - Multi-tier compliance guardrails and PII protection.
  - Strict 3-sentence answer limit and single verified official source link.
  - Live Streamlit chat integration with spinner and grounded citation displays.
- [x] **Milestone 4: Factual Accuracy & Citation Audit**:
  - Resolved historical expense ratio vs current TER distinction using Sept 2026 factsheet disclosures.
  - Grounded account statement download procedures with official guide.
  - Reconciled vector database inventory (896 chunks, 10 sources, 0 orphans).
  - Validated 15-question benchmark dataset across 7 factual criteria with 100% pass rate.
