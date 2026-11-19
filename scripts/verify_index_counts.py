"""
Detailed verification script for ChromaDB vector store:
Audits actual document IDs, chunk IDs, counts per document, and uniqueness.
"""

import sys
from pathlib import Path
from collections import Counter

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from src.config import config
from src.retriever import ChromaRetriever
from src.ingestion import DocumentIngestionPipeline


def audit_chroma_counts():
    retriever = ChromaRetriever()
    collection = retriever.get_collection()

    total_chunks = collection.count()
    print(f"\n=======================================================")
    print(f" CHROMADB VECTOR AUDIT: '{config.CHROMA_COLLECTION_NAME}'")
    print(f" Total Chunks / Vectors in Collection: {total_chunks}")
    print(f"=======================================================\n")

    # Fetch all IDs and metadatas
    data = collection.get(include=["metadatas"])
    ids = data.get("ids", [])
    metas = data.get("metadatas", [])

    print(f"Total IDs retrieved: {len(ids)}")
    print(f"Total Metadatas retrieved: {len(metas)}")

    # Check ID uniqueness
    unique_ids = set(ids)
    is_unique = len(unique_ids) == len(ids)
    print(f"Unique Chunk IDs: {len(unique_ids)} (Duplicate IDs: {len(ids) - len(unique_ids)})")

    # Count chunks per source_id and scheme_name
    source_counts = Counter()
    scheme_counts = Counter()
    doctype_counts = Counter()
    source_to_title = {}

    for m in metas:
        src = m.get("source_id", "unknown")
        scheme = m.get("scheme_name", "unknown")
        doctype = m.get("document_type", "unknown")
        title = m.get("document_title", "unknown")

        source_counts[src] += 1
        scheme_counts[scheme] += 1
        doctype_counts[doctype] += 1
        source_to_title[src] = title

    print("\n--- 1. CHUNK BREAKDOWN PER DOCUMENT (source_id) ---")
    print(f"{'Source ID':<35} | {'Type':<12} | {'Chunks':<8} | Document Title")
    print("-" * 90)
    for src, count in sorted(source_counts.items()):
        title = source_to_title.get(src, "")
        # Find doc type
        sample_meta = next(m for m in metas if m.get("source_id") == src)
        dtype = sample_meta.get("document_type", "")
        print(f"{src:<35} | {dtype:<12} | {count:<8} | {title}")

    print("\n--- 2. CHUNK BREAKDOWN PER SCHEME CATEGORY ---")
    print(f"{'Scheme Name':<35} | Chunks")
    print("-" * 50)
    for scheme, count in sorted(scheme_counts.items()):
        print(f"{scheme:<35} | {count}")

    print("\n--- 3. CHUNK BREAKDOWN PER DOCUMENT TYPE ---")
    print(f"{'Document Type':<20} | Chunks")
    print("-" * 35)
    for dtype, count in sorted(doctype_counts.items()):
        print(f"{dtype:<20} | {count}")

    # Verify against raw files generated chunks
    print("\n--- 4. COMPARISON: PIPELINE GENERATED VS CHROMADB STORED ---")
    pipeline = DocumentIngestionPipeline()
    raw_files = pipeline.discover_raw_pdfs()
    print(f"Raw PDF files in data/raw/: {len(raw_files)}")

    discrepancies = []
    print(f"{'File Name':<45} | {'Raw Chunks':<10} | {'DB Chunks':<10} | Status")
    print("-" * 85)

    for pdf in raw_files:
        meta, _ = pipeline.catalog.get_metadata_for_file(pdf.name)
        source_id = meta.get("source_id", pdf.stem.lower())
        chunks, report = pipeline.process_file(pdf)
        raw_count = len(chunks)
        db_count = source_counts.get(source_id, 0)
        status = "MATCH ✅" if raw_count == db_count else "MISMATCH ❌"
        if raw_count != db_count:
            discrepancies.append((pdf.name, raw_count, db_count))
        print(f"{pdf.name:<45} | {raw_count:<10} | {db_count:<10} | {status}")

    print("\n" + "=" * 55)
    print(f"Total Unique Source Documents: {len(source_counts)}")
    print(f"Total Unique Chunks in ChromaDB: {total_chunks}")
    print(f"Discrepancies found: {len(discrepancies)}")
    print("=" * 55 + "\n")


if __name__ == "__main__":
    audit_chroma_counts()
