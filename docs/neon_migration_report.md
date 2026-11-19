# Neon PostgreSQL & pgvector Knowledge Base Migration Report
**Groww Mutual Fund FAQ Assistant**  
**Migration Date:** November 19, 2026  
**Status:** Completed & Fully Reconciled (100% Match)

---

## 1. Executive Summary

This report documents the migration of the vector knowledge base for the **Groww Mutual Fund FAQ Assistant** from a local ChromaDB persistent collection (`hdfc_mutual_fund_knowledge`) to a cloud-hosted **Neon PostgreSQL** database with **pgvector**.

### Key Highlights
- **Zero API Invocations:** The migration reused 100% of the existing 3072-dimensional embeddings stored in ChromaDB. No Gemini embedding APIs were invoked, safeguarding against rate limits and quota depletion.
- **Exact Count & ID Reconciliation:** ChromaDB had **896** records and **896** unique chunk IDs; Neon PostgreSQL now holds exactly **896** records and **896** unique chunk IDs. Zero records were lost, orphaned, or duplicated.
- **Full Precision & HNSW Indexing:** All embeddings are stored at full precision in a `vector(3072)` column. Fast approximate nearest neighbor search is enabled via an HNSW expression index using `halfvec(3072)` with `halfvec_cosine_ops`, bypassing pgvector's standard 2,000-dimension index limitation without truncating data.
- **High Availability & Quota Resilience:** The retriever implements semantic cosine similarity with a seamless full-text keyword retrieval fallback, ensuring uninterrupted operation during external API downtime or quota exhaustion.
- **Untouched ChromaDB Backup:** The original ChromaDB persistent directory (`data/chroma_db/`) was preserved intact as a rollback target.

---

## 2. Pre-Migration Inspection

Before running the migration, the actual ChromaDB collection was inspected directly:

| Metric | Inspected Value | Notes |
| :--- | :--- | :--- |
| **ChromaDB Path** | `data/chroma_db` | PersistentClient |
| **Collection Name** | `hdfc_mutual_fund_knowledge` | Active production collection |
| **Total Stored Records** | `896` | Validated actual count (reconciles with accuracy audit) |
| **Unique Chunk IDs** | `896` | Zero duplicate IDs |
| **Unique Source Documents** | `10` | 9 official HDFC PDFs + 1 Statement & CAS Download Guide |
| **Embedding Dimension** | `3072` | Generated via `gemini-embedding-001` |
| **Missing Embeddings** | `0` | All 896 chunks contain non-null 3072-dim vectors |

---

## 3. Database & Schema Design

### 3.1 Database Environment
- **Host:** Neon PostgreSQL 18.7 (`ep-***-pooler.c-9.us-east-2.aws.neon.tech/neondb`)
- **pgvector Extension Version:** `0.8.7`
- **Connection Management:** Psycopg 3 (`psycopg[binary]>=3.2.0`) with SSL (`sslmode=require&channel_binding=require`)

### 3.2 Table Definition: `documents`
```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS documents (
    id SERIAL PRIMARY KEY,
    chunk_id VARCHAR(255) UNIQUE NOT NULL,
    content TEXT NOT NULL,
    scheme_name VARCHAR(255) NOT NULL,
    document_type VARCHAR(100) NOT NULL,
    document_title VARCHAR(500) NOT NULL,
    source_id VARCHAR(255) NOT NULL,
    source_url TEXT NOT NULL,
    published_date VARCHAR(50),
    accessed_date VARCHAR(50),
    page_number INTEGER NOT NULL,
    metadata JSONB DEFAULT '{}'::jsonb,
    embedding vector(3072) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
```

### 3.3 Index Strategy
1. **HNSW Vector Cosine Index:**
   ```sql
   CREATE INDEX IF NOT EXISTS idx_documents_embedding_hnsw 
   ON documents USING hnsw ((embedding::halfvec(3072)) halfvec_cosine_ops);
   ```
   *Rationale:* Standard PostgreSQL `vector` HNSW indexes cap at 2,000 dimensions. Using pgvector 0.8.7's `halfvec(3072)` expression index allows high-performance vector indexing for 3072-dimensional embeddings while preserving full 32-bit floating point precision in the underlying `vector(3072)` column.
2. **Metadata Filtering Indexes:**
   ```sql
   CREATE INDEX IF NOT EXISTS idx_documents_scheme ON documents (scheme_name);
   CREATE INDEX IF NOT EXISTS idx_documents_source ON documents (source_id);
   CREATE INDEX IF NOT EXISTS idx_documents_pub_date ON documents (published_date);
   ```
3. **Full-Text Search Index (Fallback Acceleration):**
   ```sql
   CREATE INDEX IF NOT EXISTS idx_documents_content_fts 
   ON documents USING gin (to_tsvector('english', content));
   ```

---

## 4. Migration Execution

The migration was performed using `scripts/migrate_chroma_to_neon.py` with batch size of 100 and transactional commits.

### Migration Log Summary
- **Start Time:** 2026-11-19 13:04:14
- **Source:** ChromaDB (`hdfc_mutual_fund_knowledge`, 896 records)
- **Batch 1 (1–100):** Committed
- **Batch 2 (101–200):** Committed
- **Batch 3 (201–300):** Committed
- **Batch 4 (301–400):** Committed
- **Batch 5 (401–500):** Committed
- **Batch 6 (501–600):** Committed
- **Batch 7 (601–700):** Committed
- **Batch 8 (701–800):** Committed
- **Batch 9 (801–896):** Committed
- **Total Processed:** 896 chunks
- **Total Inserted/Updated:** 896
- **Total Failures:** 0
- **Duration:** 4 minutes 54 seconds

---

## 5. Post-Migration Reconciliation & Validation

| Reconciliation Check | ChromaDB | Neon PostgreSQL | Status |
| :--- | :--- | :--- | :---: |
| **Total Record Count** | 896 | 896 | **EXACT MATCH** |
| **Unique Chunk IDs** | 896 | 896 | **EXACT MATCH** |
| **Missing IDs in Neon** | 0 | 0 | **PASSED** |
| **Orphan IDs in Neon** | 0 | 0 | **PASSED** |
| **Missing Embeddings** | 0 | 0 | **PASSED** |
| **Vector Dimensions** | 3072 | 3072 (all 896 rows) | **EXACT MATCH** |
| **Missing / Invalid URLs** | 0 | 0 (all start with `https://`) | **PASSED** |
| **Schemes Represented** | 6 categories | 6 categories | **EXACT MATCH** |

### Schemes Successfully Indexed in Neon
1. `HDFC Nifty 50 Index Fund` (SID, KIM, Factsheet)
2. `HDFC Flexi Cap Fund` (SID, KIM, Factsheet)
3. `HDFC ELSS Tax Saver Fund` (SID, KIM, Factsheet)
4. `General / Portfolio Facts` (Monthly Factsheet September 2026)
5. `Index Funds / Portfolio Facts` (Index Factsheet September 2026)
6. `General Account Operations` (Common Transaction Form, Statement & CAS Download Guide)

---

## 6. Retriever Implementation (`NeonRetriever`)

The new Neon retriever (`src/neon_retriever.py`) preserves all production features of the original RAG retriever:

1. **Semantic Cosine Search:**
   Calculates cosine distance via `(embedding::halfvec(3072) <=> query_vector::halfvec(3072))` utilizing the HNSW index.
2. **Scheme Filtering & Isolation:**
   When a scheme filter is provided (e.g. `HDFC Flexi Cap Fund`), queries are strictly partitioned by `scheme_name = %(scheme)s`, preventing cross-scheme data leakage.
3. **Recency Precedence & Factsheet Priority:**
   - 2026 disclosures receive a priority boost over historical disclosures.
   - For financial metric queries (TER, expense ratio, NAV, portfolio turnover), latest monthly factsheet chunks are promoted ahead of historical annual disclosures.
4. **Resilient Keyword Fallback:**
   When Gemini embedding APIs throw rate limits (HTTP 429) or quota errors, the retriever automatically falls back to full-text search on PostgreSQL without disrupting user queries.
5. **Dynamic Backend Configuration:**
   Controlled via environment variables:
   - `VECTOR_BACKEND=neon` (defaults to Neon PostgreSQL when `DATABASE_URL` is set)
   - `VECTOR_BACKEND=chroma` (seamlessly toggles back to ChromaDB)

---

## 7. Test Suite Verification

A dedicated test suite (`tests/test_neon_retriever.py`) was created and executed:

| Test Case | Description | Result |
| :--- | :--- | :---: |
| `test_database_connection` | Confirms connectivity to Neon pooler endpoint | **PASSED** |
| `test_pgvector_extension_and_halfvec` | Verifies pgvector >= 0.7 & halfvec support | **PASSED** |
| `test_documents_table_and_indexes` | Verifies table schema and HNSW/btree/gin indexes | **PASSED** |
| `test_vector_dimensions_exact_3072` | Asserts all 896 records have `vector_dims == 3072` | **PASSED** |
| `test_retriever_is_indexed` | Asserts `NeonRetriever.is_indexed()` returns True | **PASSED** |
| `test_scheme_isolation` | Verifies Flexi Cap query never leaks Nifty 50 chunks | **PASSED** |
| `test_citation_metadata_completeness` | Verifies URL, title, page, and pub_date on all results | **PASSED** |
| `test_statement_download_retrieval` | Confirms CAS/Statement guide retrieval | **PASSED** |
| `test_fallback_keyword_retrieve_on_api_exhaustion` | Tests graceful fallback when embedding API raises 429 | **PASSED** |
| `test_idempotent_upsert` | Confirms re-running insert does not duplicate records | **PASSED** |
| `test_empty_scheme_behavior` | Verifies querying non-existent scheme returns empty list | **PASSED** |

**Summary: 11 passed in 62.76s.**

---

## 8. Backup & Rollback Plan

- **Backup Integrity:** The local ChromaDB directory at `data/chroma_db/` remains completely untouched.
- **Instant Fallback:** Setting `VECTOR_BACKEND=chroma` in `.env` immediately reverts the application to the ChromaDB vector database without code modification or data re-indexing.
- **Idempotent Re-runs:** The migration script uses `ON CONFLICT (chunk_id) DO UPDATE`, allowing safe repeated executions anytime source documents are updated.

---

## 9. Conclusion

The ChromaDB to Neon PostgreSQL migration has completed with **zero discrepancies**. The system is fully operational on Neon with pgvector, preserving exact vector dimensions, metadata integrity, scheme isolation, citation accuracy, and full fallback protection against external API exhaustion.
