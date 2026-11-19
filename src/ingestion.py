"""
Document ingestion pipeline for Groww Mutual Fund FAQ Assistant.
Handles PDF text extraction with PyMuPDF, sentence-aware chunking,
metadata enrichment via docs/sources.csv, and extraction reporting.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
import csv
import hashlib
import re
import logging
from src.config import config

logger = logging.getLogger(__name__)


@dataclass
class ChunkMetadata:
    """Standard metadata schema for each document chunk."""
    source_id: str
    scheme_name: str
    document_type: str
    document_title: str
    source_url: str
    published_date: str
    accessed_date: str
    page_number: int
    chunk_id: str
    source_hash: str

    def to_dict(self) -> Dict[str, Any]:
        """Convert metadata to flat dictionary for ChromaDB storage."""
        return {
            "source_id": str(self.source_id),
            "scheme_name": str(self.scheme_name),
            "document_type": str(self.document_type),
            "document_title": str(self.document_title),
            "source_url": str(self.source_url),
            "published_date": str(self.published_date),
            "accessed_date": str(self.accessed_date),
            "page_number": int(self.page_number),
            "chunk_id": str(self.chunk_id),
            "source_hash": str(self.source_hash),
        }


@dataclass
class DocumentChunk:
    """Represents a chunk of text with metadata for vector embedding."""
    text: str
    metadata: ChunkMetadata

    @property
    def chunk_id(self) -> str:
        return self.metadata.chunk_id


@dataclass
class PDFExtractionReport:
    """Summary of extraction results for a single PDF document."""
    file_name: str
    file_path: str
    source_hash: str
    total_pages: int
    usable_pages: int
    skipped_pages: List[int]
    total_characters: int
    is_scanned: bool
    warnings: List[str] = field(default_factory=list)


class SourceCatalog:
    """Manages the official document register loaded from docs/sources.csv."""

    def __init__(self, csv_path: Optional[Path] = None):
        self.csv_path = csv_path or config.SOURCES_CSV_PATH
        self.sources: Dict[str, Dict[str, str]] = {}
        self._load_sources()

    def _load_sources(self):
        """Load sources register from CSV."""
        if not self.csv_path.exists():
            logger.warning(f"Sources register not found at {self.csv_path}")
            return

        with open(self.csv_path, mode="r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                file_name = row.get("file_name", "").strip()
                if file_name:
                    self.sources[file_name] = {k: v.strip() for k, v in row.items()}

    def get_metadata_for_file(self, file_name: str) -> Tuple[Dict[str, str], bool]:
        """
        Get metadata for a file.
        Returns (metadata_dict, is_registered_boolean).
        If missing, marks fields as 'unknown' and returns is_registered=False.
        """
        if file_name in self.sources:
            return self.sources[file_name], True

        # Fallback for unregistered files
        logger.warning(f"File '{file_name}' not found in docs/sources.csv. Marking unknown.")
        return {
            "source_id": Path(file_name).stem.lower(),
            "scheme_name": "unknown",
            "document_type": "unknown",
            "document_title": Path(file_name).stem.replace("_", " "),
            "source_url": "unknown",
            "published_date": "unknown",
            "accessed_date": "unknown",
        }, False


class DocumentIngestionPipeline:
    """High-fidelity PDF extraction and chunking pipeline."""

    def __init__(
        self,
        raw_dir: Optional[Path] = None,
        processed_dir: Optional[Path] = None,
        target_token_size: int = 800,
        token_overlap: int = 120,
    ):
        self.raw_dir = raw_dir or config.RAW_DATA_DIR
        self.processed_dir = processed_dir or config.PROCESSED_DATA_DIR
        # Approx 4 characters per token
        self.target_chars = target_token_size * 4
        self.overlap_chars = token_overlap * 4
        self.catalog = SourceCatalog()

    @staticmethod
    def compute_file_hash(file_path: Path) -> str:
        """Calculate SHA-256 hash of a file for change detection and duplicate prevention."""
        sha = hashlib.sha256()
        with open(file_path, "rb") as f:
            while chunk := f.read(65536):
                sha.update(chunk)
        return sha.hexdigest()

    def extract_pdf(self, pdf_path: Path) -> Tuple[List[Dict[str, Any]], PDFExtractionReport]:
        """
        Extract text from a PDF with page-number tracking.
        Skips empty/unusable pages and detects scanned documents.
        """
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF not found at {pdf_path}")

        try:
            import pymupdf as fitz
        except ImportError:
            import fitz

        doc = fitz.open(str(pdf_path))
        total_pages = len(doc)
        extracted_pages = []
        skipped_pages = []
        total_characters = 0
        warnings = []

        for page_idx in range(total_pages):
            page_num = page_idx + 1
            page = doc[page_idx]
            text = page.get_text("text").strip()

            # Usable text criteria: at least 20 non-whitespace characters
            if len(text) >= 20:
                extracted_pages.append({
                    "page_number": page_num,
                    "text": text,
                    "char_count": len(text),
                })
                total_characters += len(text)
            else:
                skipped_pages.append(page_num)

        doc.close()

        # Scanned PDF detection: if total characters across all pages is under 150
        is_scanned = (total_characters < 150 and total_pages > 0)
        if is_scanned:
            warnings.append(
                f"Document '{pdf_path.name}' yielded only {total_characters} text characters "
                f"across {total_pages} pages. Likely scanned document requiring OCR."
            )

        if skipped_pages:
            warnings.append(f"Skipped {len(skipped_pages)} pages with no usable text: {skipped_pages[:10]}")

        file_hash = self.compute_file_hash(pdf_path)

        report = PDFExtractionReport(
            file_name=pdf_path.name,
            file_path=str(pdf_path),
            source_hash=file_hash,
            total_pages=total_pages,
            usable_pages=len(extracted_pages),
            skipped_pages=skipped_pages,
            total_characters=total_characters,
            is_scanned=is_scanned,
            warnings=warnings,
        )

        return extracted_pages, report

    def split_into_sentences(self, text: str) -> List[str]:
        """Split text into sentences while avoiding unnecessary splits."""
        # Split on sentence boundaries: period/exclamation/question followed by space or newline
        sentences = re.split(r'(?<=[.!?])\s+', text)
        return [s.strip() for s in sentences if s.strip()]

    def chunk_page_text(
        self,
        text: str,
        page_number: int,
        source_id: str,
        source_meta: Dict[str, str],
        source_hash: str,
    ) -> List[DocumentChunk]:
        """
        Create overlapping chunks targeting approx 800 tokens (~3200 chars)
        with 120 tokens overlap (~480 chars), respecting sentence boundaries.
        Associates specific scheme names for multi-scheme factsheets.
        """
        sentences = self.split_into_sentences(text)
        if not sentences:
            return []

        # Determine scheme_name: associate specific supported scheme for multi-scheme factsheets
        base_scheme = source_meta.get("scheme_name", "unknown")
        specific_scheme = base_scheme
        text_lower = text.lower()
        if source_meta.get("document_type") == "Factsheet":
            if "hdfc flexi cap fund" in text_lower:
                specific_scheme = "HDFC Flexi Cap Fund"
            elif "hdfc elss - tax saver fund" in text_lower or "hdfc elss tax saver" in text_lower:
                specific_scheme = "HDFC ELSS Tax Saver Fund"
            elif "hdfc nifty 50 index fund" in text_lower:
                specific_scheme = "HDFC Nifty 50 Index Fund"

        chunks: List[DocumentChunk] = []
        current_chunk_sentences: List[str] = []
        current_length = 0
        chunk_idx = 0

        for sentence in sentences:
            sentence_len = len(sentence)

            # If adding this sentence exceeds target size and we already have content
            if current_length + sentence_len > self.target_chars and current_chunk_sentences:
                chunk_text = " ".join(current_chunk_sentences)
                chunk_id = f"{source_id}_p{page_number}_c{chunk_idx}"

                metadata = ChunkMetadata(
                    source_id=source_id,
                    scheme_name=specific_scheme,
                    document_type=source_meta.get("document_type", "unknown"),
                    document_title=source_meta.get("document_title", source_meta.get("official_source_title", "unknown")),
                    source_url=source_meta.get("source_url", "unknown"),
                    published_date=source_meta.get("published_date", "unknown"),
                    accessed_date=source_meta.get("accessed_date", "unknown"),
                    page_number=page_number,
                    chunk_id=chunk_id,
                    source_hash=source_hash,
                )

                chunks.append(DocumentChunk(text=chunk_text, metadata=metadata))
                chunk_idx += 1

                # Calculate overlap: keep trailing sentences up to overlap_chars
                overlap_sentences: List[str] = []
                accumulated_overlap = 0
                for s in reversed(current_chunk_sentences):
                    if accumulated_overlap + len(s) <= self.overlap_chars:
                        overlap_sentences.insert(0, s)
                        accumulated_overlap += len(s)
                    else:
                        break

                current_chunk_sentences = overlap_sentences + [sentence]
                current_length = sum(len(s) for s in current_chunk_sentences)
            else:
                current_chunk_sentences.append(sentence)
                current_length += sentence_len

        # Final remaining chunk
        if current_chunk_sentences:
            chunk_text = " ".join(current_chunk_sentences)
            chunk_id = f"{source_id}_p{page_number}_c{chunk_idx}"
            metadata = ChunkMetadata(
                source_id=source_id,
                scheme_name=specific_scheme,
                document_type=source_meta.get("document_type", "unknown"),
                document_title=source_meta.get("document_title", source_meta.get("official_source_title", "unknown")),
                source_url=source_meta.get("source_url", "unknown"),
                published_date=source_meta.get("published_date", "unknown"),
                accessed_date=source_meta.get("accessed_date", "unknown"),
                page_number=page_number,
                chunk_id=chunk_id,
                source_hash=source_hash,
            )
            chunks.append(DocumentChunk(text=chunk_text, metadata=metadata))

        return chunks

    def process_file(self, pdf_path: Path) -> Tuple[List[DocumentChunk], PDFExtractionReport]:
        """
        Process a single PDF into structured chunks with validated metadata.
        Preserves strict document boundaries.
        """
        extracted_pages, report = self.extract_pdf(pdf_path)
        source_meta, is_registered = self.catalog.get_metadata_for_file(pdf_path.name)

        if not is_registered:
            report.warnings.append(f"Metadata for '{pdf_path.name}' is unregistered in sources.csv; marked unknown.")

        source_id = source_meta.get("source_id", pdf_path.stem.lower())
        all_chunks: List[DocumentChunk] = []

        for page in extracted_pages:
            page_chunks = self.chunk_page_text(
                text=page["text"],
                page_number=page["page_number"],
                source_id=source_id,
                source_meta=source_meta,
                source_hash=report.source_hash,
            )
            all_chunks.extend(page_chunks)

        return all_chunks, report

    def discover_raw_pdfs(self) -> List[Path]:
        """Recursively discover all PDF files under data/raw/."""
        if not self.raw_dir.exists():
            return []
        return sorted(list(self.raw_dir.rglob("*.pdf")))
