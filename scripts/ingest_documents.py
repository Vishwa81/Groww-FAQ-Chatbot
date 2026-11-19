"""
Document Ingestion and Vector Indexing Runner for Groww Mutual Fund FAQ Assistant.
Can be executed as a standalone module:
    python -m scripts.ingest_documents
"""

import sys
import time
from pathlib import Path
from typing import List, Dict, Any
import logging

# Ensure project root is in sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from src.config import config
from src.ingestion import DocumentIngestionPipeline, PDFExtractionReport, DocumentChunk
from src.retriever import ChromaRetriever
from src.llm import GeminiClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("ingestion_runner")


def run_ingestion(force_reindex: bool = False) -> Dict[str, Any]:
    """
    Execute full ingestion: PDF discovery -> extraction -> chunking -> embedding -> ChromaDB indexing.
    """
    print("\n" + "=" * 70)
    print(" GROWW MUTUAL FUND FAQ ASSISTANT - INGESTION & VECTOR INDEXING")
    print(f" Target ChromaDB Collection: '{config.CHROMA_COLLECTION_NAME}'")
    print(f" Embedding Model: '{config.EMBEDDING_MODEL}'")
    print(f" Data Directory: '{config.RAW_DATA_DIR}'")
    print("=" * 70 + "\n")

    pipeline = DocumentIngestionPipeline()
    retriever = ChromaRetriever()
    llm = GeminiClient()

    if not llm.is_available():
        print("❌ ERROR: GEMINI_API_KEY is not configured in .env.")
        print("Please configure your API key before running ingestion.")
        return {"status": "error", "error": "Missing GEMINI_API_KEY"}

    pdf_files = pipeline.discover_raw_pdfs()
    if not pdf_files:
        print(f"⚠️ No PDF files found in {config.RAW_DATA_DIR}.")
        return {"status": "empty", "pdf_count": 0}

    print(f"Found {len(pdf_files)} PDF file(s) in {config.RAW_DATA_DIR}:\n")
    for f in pdf_files:
        print(f"  • {f.name} ({round(f.stat().st_size / 1024, 1)} KB)")

    total_pages_extracted = 0
    total_pages_skipped = 0
    total_chunks_created = 0
    total_chunks_indexed = 0
    skipped_duplicates_count = 0
    documents_report: List[Dict[str, Any]] = []

    print("\n--- Processing Documents ---")

    for idx, pdf_path in enumerate(pdf_files, start=1):
        file_name = pdf_path.name
        print(f"\n[{idx}/{len(pdf_files)}] Ingesting: {file_name}")

        try:
            chunks, extraction_report = pipeline.process_file(pdf_path)

            total_pages_extracted += extraction_report.usable_pages
            total_pages_skipped += len(extraction_report.skipped_pages)
            total_chunks_created += len(chunks)

            print(f"  - Pages: {extraction_report.usable_pages} usable / {extraction_report.total_pages} total")
            if extraction_report.skipped_pages:
                print(f"  - Skipped {len(extraction_report.skipped_pages)} empty page(s)")
            if extraction_report.is_scanned:
                print(f"  - ⚠️ WARNING: Scanned PDF detected, may need OCR.")
            print(f"  - Chunks generated: {len(chunks)}")

            if not chunks:
                print(f"  - ⚠️ No text chunks generated for {file_name}. Skipping indexing.")
                documents_report.append({
                    "file_name": file_name,
                    "status": "empty_chunks",
                    "usable_pages": extraction_report.usable_pages,
                    "chunks": 0,
                    "indexed": 0,
                })
                continue

            source_id = chunks[0].metadata.source_id
            source_hash = extraction_report.source_hash

            # Check if document already indexed with matching hash
            if not force_reindex and retriever.is_document_indexed_and_current(source_id, source_hash):
                print(f"  - ⏭️ Up to date: source '{source_id}' already indexed with identical hash. Skipping embedding.")
                skipped_duplicates_count += 1
                documents_report.append({
                    "file_name": file_name,
                    "status": "skipped_duplicate",
                    "usable_pages": extraction_report.usable_pages,
                    "chunks": len(chunks),
                    "indexed": 0,
                })
                continue

            # If reindexing or modified: delete old chunks
            retriever.delete_document(source_id)

            # Generate embeddings with Gemini API
            print(f"  - Generating embeddings with {config.EMBEDDING_MODEL} (batch size: 8)...")
            chunk_texts = [c.text for c in chunks]
            start_time = time.time()
            embeddings = llm.embed_batch(chunk_texts, batch_size=8)
            elapsed = time.time() - start_time
            print(f"  - Generated {len(embeddings)} embeddings in {elapsed:.1f}s")

            # Index in ChromaDB
            indexed_count = retriever.index_chunks(chunks, embeddings)
            total_chunks_indexed += indexed_count
            print(f"  - ✅ Successfully indexed {indexed_count} chunk(s) into ChromaDB")

            documents_report.append({
                "file_name": file_name,
                "status": "indexed",
                "usable_pages": extraction_report.usable_pages,
                "chunks": len(chunks),
                "indexed": indexed_count,
            })

        except Exception as e:
            logger.error(f"Failed processing {file_name}: {e}", exc_info=True)
            print(f"  - ❌ ERROR: {e}")
            documents_report.append({
                "file_name": file_name,
                "status": f"error: {str(e)}",
                "usable_pages": 0,
                "chunks": 0,
                "indexed": 0,
            })

    # Final Summary Report
    print("\n" + "=" * 70)
    print(" INGESTION & INDEXING SUMMARY REPORT")
    print("=" * 70)
    print(f"Total PDFs Processed:       {len(pdf_files)}")
    print(f"Total Pages Extracted:      {total_pages_extracted}")
    print(f"Total Pages Skipped:        {total_pages_skipped}")
    print(f"Total Chunks Created:       {total_chunks_created}")
    print(f"Total Chunks Newly Indexed: {total_chunks_indexed}")
    print(f"Documents Already Current:  {skipped_duplicates_count}")
    print(f"Current ChromaDB Count:     {retriever.get_document_count()}")
    print("=" * 70 + "\n")

    return {
        "status": "success",
        "total_pdfs": len(pdf_files),
        "total_pages_extracted": total_pages_extracted,
        "total_pages_skipped": total_pages_skipped,
        "total_chunks_created": total_chunks_created,
        "total_chunks_indexed": total_chunks_indexed,
        "documents_report": documents_report,
        "collection_total_count": retriever.get_document_count(),
    }


if __name__ == "__main__":
    force_flag = "--force" in sys.argv
    run_ingestion(force_reindex=force_flag)
