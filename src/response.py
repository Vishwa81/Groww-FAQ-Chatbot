"""
Response generation module for Groww Mutual Fund FAQ Assistant.
Orchestrates guardrails, ChromaDB retrieval, Gemini LLM generation,
3-sentence answer constraint, and verified source grounding.
"""

from typing import Dict, Any, List, Optional
import re
import logging
from src.config import config
from src.guardrails import GuardrailEngine, QueryIntent, EDUCATIONAL_RESOURCE_URL, GROWW_HELP_URL
from src.retriever import ChromaRetriever
from src.llm import GeminiClient
from src.prompts import SYSTEM_PROMPT, RAG_USER_PROMPT_TEMPLATE

logger = logging.getLogger(__name__)


def count_and_limit_sentences(text: str, max_sentences: int = 3) -> str:
    """Split text into sentences and truncate to max_sentences if exceeded."""
    if not text:
        return ""
    # Split on sentence terminals followed by whitespace
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    clean_sentences = [s.strip() for s in sentences if s.strip()]
    if len(clean_sentences) <= max_sentences:
        return " ".join(clean_sentences)
    return " ".join(clean_sentences[:max_sentences])


class FAQResponseService:
    """Orchestrates query classification, retrieval, and grounded response synthesis."""

    def __init__(
        self,
        retriever: Optional[Any] = None,
        llm_client: Optional[GeminiClient] = None,
    ):
        self.llm = llm_client or GeminiClient()
        if retriever is not None:
            self.retriever = retriever
        elif config.is_db_configured() and config.VECTOR_BACKEND == "neon":
            try:
                from src.neon_retriever import NeonRetriever
                self.retriever = NeonRetriever(llm_client=self.llm)
            except Exception as e:
                logger.warning(f"Could not initialize NeonRetriever ({e}). Falling back to ChromaRetriever.")
                self.retriever = ChromaRetriever(llm_client=self.llm)
        else:
            self.retriever = ChromaRetriever(llm_client=self.llm)

    def process_query(self, user_query: str, scheme_filter: Optional[str] = None) -> Dict[str, Any]:
        """
        Process user query through compliance guardrails and RAG pipeline.
        
        Returns a dictionary containing:
        - status: 'success', 'refusal', 'no_context', or 'error'
        - answer_body: Direct answer (max 3 sentences)
        - source_link: Verified official URL
        - document_title: Official document name
        - page_number: Page number in official PDF
        - last_updated: Document publication date(s)
        - formatted_response: Clean markdown response
        - citations: List of source references
        - intent: Identified query intent
        """
        # 1. Evaluate Guardrails (PII, Advice, Comparisons, Scope)
        intent, refusal_message, resource_url = GuardrailEngine.classify_query(user_query)

        if intent != QueryIntent.FACTUAL_QUERY:
            refusal_body = refusal_message
            formatted_refusal = (
                f"{refusal_body}\n\n"
                f"🔗 **Official Resource**: [{resource_url}]({resource_url})"
            )
            return {
                "status": "refusal",
                "answer_body": refusal_body,
                "source_link": resource_url,
                "document_title": "Official Guidance",
                "page_number": None,
                "last_updated": "Current",
                "formatted_response": formatted_refusal,
                "citations": [resource_url],
                "intent": intent.value,
                "rag_status": "bypassed_guardrail",
            }

        # 2. Check Vector Database Indexing
        if not self.retriever.is_indexed():
            msg = (
                "The official mutual fund knowledge base is currently being updated. "
                "Please run `python -m scripts.ingest_documents` to index official documents."
            )
            return {
                "status": "error",
                "answer_body": msg,
                "source_link": GROWW_HELP_URL,
                "document_title": "System Notification",
                "page_number": None,
                "last_updated": "Date not available",
                "formatted_response": f"{msg}\n\n🔗 [{GROWW_HELP_URL}]({GROWW_HELP_URL})",
                "citations": [],
                "intent": intent.value,
                "rag_status": "unindexed",
            }

        # 3. Check LLM Client Availability
        if not self.llm.is_available():
            msg = "Gemini API key is not configured in `.env`. Please configure GEMINI_API_KEY."
            return {
                "status": "error",
                "answer_body": msg,
                "source_link": GROWW_HELP_URL,
                "document_title": "System Configuration",
                "page_number": None,
                "last_updated": "Date not available",
                "formatted_response": msg,
                "citations": [],
                "intent": intent.value,
                "rag_status": "missing_api_key",
            }

        # 4. Perform Semantic Retrieval (Max 5 Chunks, Date-Sorted)
        try:
            chunks = self.retriever.retrieve(user_query, n_results=5, scheme_filter=scheme_filter)
            if not chunks:
                no_context_msg = "The requested information could not be verified from the available official sources."
                formatted = (
                    f"{no_context_msg}\n\n"
                    f"Last updated from sources: Date not available\n\n"
                    f"🔗 **Reference Portal**: [{GROWW_HELP_URL}]({GROWW_HELP_URL})"
                )
                return {
                    "status": "no_context",
                    "answer_body": no_context_msg,
                    "source_link": GROWW_HELP_URL,
                    "document_title": "Official Portal",
                    "page_number": None,
                    "last_updated": "Date not available",
                    "formatted_response": formatted,
                    "citations": [],
                    "intent": intent.value,
                    "rag_status": "no_chunks_retrieved",
                }

            # Collect source dates and verified URLs
            dates = sorted(list(set(c["published_date"] for c in chunks if c.get("published_date") and c["published_date"] != "Date not available")), reverse=True)
            last_updated_str = ", ".join(dates) if dates else "Date not available"

            # Primary verified reference (most relevant / top chunk)
            primary_chunk = chunks[0]
            source_url = primary_chunk.get("source_url") or GROWW_HELP_URL
            doc_title = primary_chunk.get("document_title", "Official Scheme Document")
            page_num = primary_chunk.get("page_number", 1)

            # Build formatted context block
            context_blocks = []
            for c in chunks:
                context_blocks.append(
                    f"[{c['document_title']}, Page {c['page_number']}, Published: {c['published_date']}]\n"
                    f"{c['text']}"
                )
            context_text = "\n\n---\n\n".join(context_blocks)

            # 5. Generate Grounded Response with Gemini
            prompt = RAG_USER_PROMPT_TEMPLATE.format(context=context_text, question=user_query)
            raw_response = self.llm.generate_answer(prompt=prompt, system_instruction=SYSTEM_PROMPT)

            # Parse answer body and separate metadata
            raw_lines = raw_response.strip().split("\n")
            body_lines = []
            for line in raw_lines:
                # Stop when reaching source/link/update metadata lines
                if any(line.strip().lower().startswith(prefix) for prefix in ["source:", "link:", "last updated", "🔗"]):
                    continue
                if line.strip():
                    body_lines.append(line.strip())

            raw_body = " ".join(body_lines) if body_lines else raw_response.strip()

            # Enforce strict 3-sentence maximum length
            answer_body = count_and_limit_sentences(raw_body, max_sentences=3)

            # Citation validation: check if answer states the information is unverified
            unverified_signals = [
                "could not be verified",
                "cannot be verified",
                "could not be found",
                "cannot be found",
                "not found in the official",
                "not found in the available",
                "no official information",
                "information is not available",
                "not mentioned in the",
                "not provided in the",
            ]
            is_unverified = any(sig in answer_body.lower() for sig in unverified_signals)

            if is_unverified:
                # Do not fabricate or attach an unrelated document citation for unverified answers
                formatted_response = (
                    f"{answer_body}\n\n"
                    f"---\n"
                    f"🔗 **Reference Portal**: [{GROWW_HELP_URL}]({GROWW_HELP_URL})\n"
                    f"📅 **Last updated from sources**: Date not available"
                )
                return {
                    "status": "unverified",
                    "answer_body": answer_body,
                    "source_link": GROWW_HELP_URL,
                    "document_title": "None (Unverified in available sources)",
                    "page_number": None,
                    "last_updated": "Date not available",
                    "formatted_response": formatted_response,
                    "citations": [],
                    "intent": intent.value,
                    "rag_status": "unverified_evidence",
                }

            # Grounding verification: score chunks by keyword, entity, number, and date recency
            stopwords = {
                "about", "after", "again", "against", "all", "also", "and", "any", "are", "because",
                "been", "before", "being", "between", "both", "but", "by", "can", "could", "did",
                "do", "does", "doing", "down", "during", "each", "few", "for", "from", "further",
                "had", "has", "have", "having", "he", "her", "here", "hers", "herself", "him",
                "himself", "his", "how", "if", "in", "into", "is", "it", "its", "itself", "just",
                "me", "more", "most", "my", "myself", "no", "nor", "not", "now", "of", "off", "on",
                "once", "only", "or", "other", "our", "ours", "ourselves", "out", "over", "own",
                "same", "she", "should", "so", "some", "such", "than", "that", "the", "their",
                "theirs", "them", "themselves", "then", "there", "these", "they", "this", "those",
                "through", "to", "too", "under", "until", "up", "very", "was", "we", "were", "what",
                "when", "where", "which", "while", "who", "whom", "why", "with", "would", "you",
                "your", "yours", "yourself", "yourselves"
            }
            answer_numbers = set(re.findall(r"\b\d+(?:\.\d+)?%?\b", answer_body))
            answer_keywords = set(re.findall(r"\b[a-zA-Z]{3,}\b", answer_body.lower())) - stopwords

            def score_chunk_grounding(chunk: dict) -> float:
                c_text = chunk.get("text", "").lower()
                c_words = set(re.findall(r"\b[a-zA-Z]{3,}\b", c_text))
                
                score = 0.0
                # Specific percentage and number grounding (highest precision)
                for num in answer_numbers:
                    if num.lower() in c_text:
                        score += 10.0
                
                # Semantic vocabulary overlap
                score += len(answer_keywords.intersection(c_words))
                
                # Prefer latest official disclosure for time-sensitive queries
                pub_date = chunk.get("published_date", "")
                if "2026" in pub_date:
                    score += 15.0
                elif "2025" in pub_date:
                    score += 5.0
                    
                return score

            best_chunk = chunks[0]
            best_score = -1.0

            for c in chunks:
                s = score_chunk_grounding(c)
                if s > best_score:
                    best_score = s
                    best_chunk = c

            matching_chunk = best_chunk
            source_url = matching_chunk.get("source_url") or GROWW_HELP_URL
            doc_title = matching_chunk.get("document_title", "Official Scheme Document")
            page_num = matching_chunk.get("page_number", 1)
            chunk_date = matching_chunk.get("published_date") or last_updated_str

            # Format final clean response for display with verified citation
            formatted_response = (
                f"{answer_body}\n\n"
                f"---\n"
                f"📄 **Document**: {doc_title} (Page {page_num})\n"
                f"🔗 **Official Source**: [{doc_title}]({source_url})\n"
                f"📅 **Last updated from sources**: {last_updated_str}"
            )

            citations = [f"{matching_chunk['document_title']} (Page {matching_chunk['page_number']})"]

            return {
                "status": "success",
                "answer_body": answer_body,
                "source_link": source_url,
                "document_title": doc_title,
                "page_number": page_num,
                "last_updated": last_updated_str,
                "formatted_response": formatted_response,
                "citations": citations,
                "intent": intent.value,
                "rag_status": "ready",
            }

        except Exception as e:
            logger.error(f"Error in RAG generation: {e}", exc_info=True)
            err_msg = f"An error occurred while retrieving official records: {str(e)}"
            return {
                "status": "error",
                "answer_body": err_msg,
                "source_link": GROWW_HELP_URL,
                "document_title": "System Error",
                "page_number": None,
                "last_updated": "Date not available",
                "formatted_response": err_msg,
                "citations": [],
                "intent": intent.value,
                "rag_status": "error",
            }


# Singleton service instance
response_service = FAQResponseService()


def generate_rag_response(query: str, scheme_filter: Optional[str] = None) -> Dict[str, Any]:
    """Convenience helper to process query through the singleton FAQResponseService."""
    return response_service.process_query(query, scheme_filter=scheme_filter)

