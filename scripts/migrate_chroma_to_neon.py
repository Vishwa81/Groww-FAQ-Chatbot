"""
Migration Script: ChromaDB to Neon PostgreSQL with pgvector.

Extracts all documents, metadata, and 3072-dimensional vector embeddings
from local ChromaDB collection (hdfc_mutual_fund_knowledge) and migrates them
directly to Neon PostgreSQL.

Guarantees:
- ZERO calls to Gemini embedding APIs (no vector regeneration).
- Full precision vector(3072) storage with halfvec(3072) HNSW cosine index.
- Batch processing with atomic transactions and rollback on failure.
- 100% idempotent via ON CONFLICT (chunk_id) DO UPDATE.
- Secrets are masked; credentials are never logged.
- Validates pre- and post-migration record reconciliation.
"""

import sys
import json
import logging
from typing import Dict, Any, List, Tuple
from pathlib import Path
import chromadb
import psycopg
from pgvector.psycopg import register_vector
from src.config import config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("chroma_to_neon_migration")

# PostgreSQL Schema Definitions
CREATE_EXTENSION_SQL = "CREATE EXTENSION IF NOT EXISTS vector;"

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS documents (
    id BIGSERIAL PRIMARY KEY,
    chunk_id VARCHAR(255) UNIQUE NOT NULL,
    content TEXT NOT NULL,
    scheme_name VARCHAR(255) NOT NULL,
    document_type VARCHAR(100),
    document_title VARCHAR(255) NOT NULL,
    source_id VARCHAR(100) NOT NULL,
    source_url TEXT NOT NULL,
    published_date VARCHAR(50),
    accessed_date VARCHAR(50),
    page_number INTEGER NOT NULL DEFAULT 1,
    metadata JSONB DEFAULT '{}'::jsonb,
    embedding vector(3072) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_INDEXES_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_documents_scheme ON documents (scheme_name);",
    "CREATE INDEX IF NOT EXISTS idx_documents_source ON documents (source_id);",
    "CREATE INDEX IF NOT EXISTS idx_documents_pubdate ON documents (published_date);",
    "CREATE INDEX IF NOT EXISTS idx_documents_fts ON documents USING gin (to_tsvector('english', content));",
    "CREATE INDEX IF NOT EXISTS idx_documents_embedding_hnsw ON documents USING hnsw ((embedding::halfvec(3072)) halfvec_cosine_ops);",
]

UPSERT_DOCUMENT_SQL = """
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
    content = EXCLUDED.content,
    scheme_name = EXCLUDED.scheme_name,
    document_type = EXCLUDED.document_type,
    document_title = EXCLUDED.document_title,
    source_id = EXCLUDED.source_id,
    source_url = EXCLUDED.source_url,
    published_date = EXCLUDED.published_date,
    accessed_date = EXCLUDED.accessed_date,
    page_number = EXCLUDED.page_number,
    metadata = EXCLUDED.metadata,
    embedding = EXCLUDED.embedding;
"""


def init_neon_schema(conn: psycopg.Connection) -> None:
    """Initialize pgvector extension, documents table, and indexes."""
    logger.info("Initializing Neon PostgreSQL schema and pgvector extension...")
    with conn.cursor() as cur:
        cur.execute(CREATE_EXTENSION_SQL)
        cur.execute(CREATE_TABLE_SQL)
        for idx_sql in CREATE_INDEXES_SQL:
            cur.execute(idx_sql)
    conn.commit()
    logger.info("Schema, tables, and indexes initialized successfully.")


def extract_from_chroma(persist_dir: Path, collection_name: str) -> Dict[str, Any]:
    """Extract all records and pre-calculated vectors from ChromaDB collection."""
    logger.info(f"Opening ChromaDB at: {persist_dir} (Collection: {collection_name})")
    client = chromadb.PersistentClient(path=str(persist_dir))
    collection = client.get_collection(collection_name)
    
    total_count = collection.count()
    logger.info(f"Inspected ChromaDB collection: {total_count} records found.")
    
    # Retrieve all records with embeddings, metadatas, and documents
    data = collection.get(include=["metadatas", "embeddings", "documents"])
    return data


def migrate_to_neon(
    chroma_data: Dict[str, Any],
    db_url: str,
    batch_size: int = 100
) -> Tuple[int, int]:
    """
    Migrate Chroma records to Neon PostgreSQL in transactional batches.
    Returns: (total_migrated, total_failed)
    """
    ids = chroma_data["ids"]
    docs = chroma_data["documents"]
    metas = chroma_data["metadatas"]
    embs = chroma_data["embeddings"]
    total = len(ids)

    logger.info(f"Connecting to Neon at {config.get_safe_db_url()}...")
    total_migrated = 0
    total_failed = 0

    with psycopg.connect(db_url) as conn:
        register_vector(conn)
        init_neon_schema(conn)

        for start_idx in range(0, total, batch_size):
            end_idx = min(start_idx + batch_size, total)
            batch_slice = range(start_idx, end_idx)
            batch_params = []

            for i in batch_slice:
                cid = ids[i]
                content = docs[i]
                meta = metas[i] or {}
                emb = embs[i]

                # Validate embedding dimension
                if len(emb) != 3072:
                    logger.error(f"Invalid embedding dimension {len(emb)} for chunk {cid}! Expected 3072.")
                    total_failed += 1
                    continue

                batch_params.append({
                    "chunk_id": cid,
                    "content": content,
                    "scheme_name": meta.get("scheme_name", "General / Portfolio Facts"),
                    "document_type": meta.get("document_type", "Document"),
                    "document_title": meta.get("document_title", "Official Scheme Document"),
                    "source_id": meta.get("source_id", "unknown"),
                    "source_url": meta.get("source_url", "https://www.hdfcfund.com"),
                    "published_date": meta.get("published_date", "Date not available"),
                    "accessed_date": meta.get("accessed_date", "Date not available"),
                    "page_number": int(meta.get("page_number", 1)),
                    "metadata": json.dumps(meta),
                    "embedding": emb,
                })

            # Execute transactional batch
            try:
                with conn.transaction():
                    with conn.cursor() as cur:
                        for p in batch_params:
                            cur.execute(UPSERT_DOCUMENT_SQL, p)
                total_migrated += len(batch_params)
                logger.info(f"Migrated batch {start_idx + 1}-{end_idx} of {total} chunks.")
            except Exception as e:
                logger.error(f"Transaction failed for batch {start_idx}-{end_idx}: {e}")
                total_failed += len(batch_params)

    return total_migrated, total_failed


def validate_migration(chroma_data: Dict[str, Any], db_url: str) -> Dict[str, Any]:
    """Validate Neon data against ChromaDB data."""
    logger.info("Executing post-migration validation against Neon PostgreSQL...")
    chroma_ids = set(chroma_data["ids"])
    chroma_count = len(chroma_ids)

    with psycopg.connect(db_url) as conn:
        register_vector(conn)
        with conn.cursor() as cur:
            # 1. Total row count
            cur.execute("SELECT COUNT(*) FROM documents;")
            neon_count = cur.fetchone()[0]

            # 2. Unique chunk_id count
            cur.execute("SELECT COUNT(DISTINCT chunk_id) FROM documents;")
            neon_unique_chunks = cur.fetchone()[0]

            # 3. Retrieve all Neon chunk IDs
            cur.execute("SELECT chunk_id, vector_dims(embedding), source_url, scheme_name FROM documents;")
            rows = cur.fetchall()

            neon_ids = set(r[0] for r in rows)
            neon_dims = set(r[1] for r in rows)
            neon_missing_url = sum(1 for r in rows if not r[2] or not r[2].startswith("https://"))
            neon_schemes = set(r[3] for r in rows)

    orphans_in_neon = neon_ids - chroma_ids
    missing_in_neon = chroma_ids - neon_ids

    report = {
        "chroma_record_count": chroma_count,
        "neon_record_count": neon_count,
        "chroma_unique_ids": len(chroma_ids),
        "neon_unique_ids": neon_unique_chunks,
        "counts_match": (chroma_count == neon_count),
        "ids_reconciled": (len(missing_in_neon) == 0 and len(orphans_in_neon) == 0),
        "missing_in_neon_count": len(missing_in_neon),
        "orphans_in_neon_count": len(orphans_in_neon),
        "neon_embedding_dimensions": list(neon_dims),
        "all_embeddings_3072": (neon_dims == {3072}),
        "missing_or_invalid_urls": neon_missing_url,
        "schemes_indexed": sorted(list(neon_schemes)),
    }
    return report


def main():
    logger.info("=== Starting ChromaDB to Neon PostgreSQL Migration ===")
    
    if not config.DATABASE_URL:
        logger.error("DATABASE_URL is not set in environment or .env! Migration cannot proceed.")
        sys.exit(1)

    # 1. Inspect & Extract from ChromaDB
    chroma_data = extract_from_chroma(
        persist_dir=config.CHROMA_PERSIST_DIR,
        collection_name=config.CHROMA_COLLECTION_NAME
    )
    chroma_count = len(chroma_data["ids"])

    if chroma_count == 0:
        logger.error("ChromaDB collection is empty! Nothing to migrate.")
        sys.exit(1)

    # 2. Execute Migration
    migrated, failed = migrate_to_neon(
        chroma_data=chroma_data,
        db_url=config.DATABASE_URL,
        batch_size=100
    )
    logger.info(f"Migration completed. Successfully inserted/updated: {migrated}, Failed: {failed}")

    # 3. Validate
    validation = validate_migration(chroma_data, config.DATABASE_URL)
    logger.info("=== Post-Migration Validation Results ===")
    logger.info(json.dumps(validation, indent=2))

    if validation["counts_match"] and validation["ids_reconciled"] and validation["all_embeddings_3072"]:
        logger.info("✅ MIGRATION SUCCESSFUL! All records, vectors, and metadata reconciled perfectly.")
    else:
        logger.error("❌ MIGRATION VALIDATION FAILED! Please inspect reconciliation discrepancies.")
        sys.exit(1)


if __name__ == "__main__":
    main()
