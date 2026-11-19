"""
LLM and Embedding Client wrapper for Google Gemini API.
Handles client initialization, model invocation, batch embeddings,
rate limit retries with exponential backoff, and dimension validation.
"""

from typing import Optional, List
import time
import re
import logging
from src.config import config

logger = logging.getLogger(__name__)


def extract_retry_delay(exc: Exception, default_delay: float) -> float:
    """Extract suggested retry delay from Gemini API 429 quota error if present."""
    msg = str(exc)
    # Check for 'Please retry in 13.4859s' or long delays
    match = re.search(r"retry in\s+([\d\.]+)\s*s", msg, re.IGNORECASE)
    if match:
        try:
            delay = float(match.group(1)) + 1.5
            if delay > 30.0:
                raise RuntimeError(f"Gemini API quota exhausted (delay {delay:.0f}s requested). {msg}")
            return delay
        except ValueError:
            pass
    # Check for "retryDelay': '13s'" or '7799s'
    match_sec = re.search(r"retryDelay':\s*'(\d+)s'", msg)
    if match_sec:
        try:
            delay = float(match_sec.group(1)) + 1.5
            if delay > 30.0:
                raise RuntimeError(f"Gemini API daily quota limit reached: {msg}")
            return delay
        except ValueError:
            pass
    if "per day limit exceeded" in msg.lower() or "daily" in msg.lower():
        raise RuntimeError(f"Gemini API daily quota limit reached: {msg}")
    return default_delay


class GeminiClient:
    """Wrapper around Google Gemini API for generation and embeddings."""

    EXPECTED_EMBEDDING_DIM = 3072
    _EMBED_CACHE = {}

    def __init__(
        self,
        api_key: Optional[str] = None,
        model_name: Optional[str] = None,
        embedding_model: Optional[str] = None,
    ):
        self.api_key = api_key or config.GEMINI_API_KEY
        self.model_name = model_name or config.LLM_MODEL
        self.embedding_model = embedding_model or config.EMBEDDING_MODEL
        self._client = None

    def is_available(self) -> bool:
        """Check if API key is provided and valid format."""
        return bool(self.api_key and self.api_key.strip() != "your_gemini_api_key_here")

    def _init_client(self):
        """Initialize Google GenAI client."""
        if not self.is_available():
            raise ValueError(
                "Gemini API key is not configured. Please set GEMINI_API_KEY in your .env file."
            )

        if self._client is None:
            try:
                from google import genai
                self._client = genai.Client(api_key=self.api_key)
            except ImportError:
                raise ImportError(
                    "The official 'google-genai' SDK is required. Please run: pip install google-genai"
                )
        return self._client

    def generate_answer(self, prompt: str, system_instruction: Optional[str] = None, max_retries: int = 3) -> str:
        """Generate grounded answer using Gemini LLM with automatic retry and transient error handling."""
        client = self._init_client()
        from google.genai import types
        from google.genai import errors

        config_params = {}
        if system_instruction:
            config_params["system_instruction"] = system_instruction

        models_to_try = [self.model_name]
        if self.model_name != "gemini-3.1-flash-lite":
            models_to_try.append("gemini-3.1-flash-lite")

        last_error = None
        for model in models_to_try:
            for attempt in range(max_retries):
                try:
                    response = client.models.generate_content(
                        model=model,
                        contents=prompt,
                        config=types.GenerateContentConfig(**config_params) if config_params else None
                    )
                    return response.text or ""
                except (errors.ServerError, errors.ClientError) as e:
                    last_error = e
                    err_msg = str(e)
                    if "503" in err_msg or "429" in err_msg:
                        logger.warning(f"Transient {model} error ({err_msg}). Retrying in {1.5 * (attempt + 1)}s...")
                        time.sleep(1.5 * (attempt + 1))
                        continue
                    raise e
                except Exception as e:
                    last_error = e
                    time.sleep(1.5)

        raise last_error or RuntimeError("Failed to generate answer after retries.")

    def embed_text(self, text: str, max_retries: int = 5) -> List[float]:
        """Generate vector embedding for a single text using gemini-embedding-001 with cache."""
        key = text.strip()
        if key in self._EMBED_CACHE:
            return self._EMBED_CACHE[key]
        embeddings = self.embed_batch([text], max_retries=max_retries)
        if embeddings:
            self._EMBED_CACHE[key] = embeddings[0]
            return embeddings[0]
        raise RuntimeError("Failed to generate embedding for input text.")

    def embed_batch(
        self,
        texts: List[str],
        batch_size: int = 8,
        max_retries: int = 8,
        base_delay: float = 2.0,
    ) -> List[List[float]]:
        """
        Generate vector embeddings in batches with exponential backoff on rate limits.
        Enforces consistent embedding dimensions.
        """
        if not texts:
            return []

        client = self._init_client()
        all_embeddings: List[List[float]] = []

        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            success = False
            delay = base_delay

            for attempt in range(max_retries):
                try:
                    response = client.models.embed_content(
                        model=self.embedding_model,
                        contents=batch,
                    )

                    batch_vectors = []
                    for emb in response.embeddings:
                        vec = list(emb.values)
                        if len(vec) != self.EXPECTED_EMBEDDING_DIM:
                            logger.warning(
                                f"Unexpected embedding dimension: {len(vec)} "
                                f"(expected {self.EXPECTED_EMBEDDING_DIM})"
                            )
                        batch_vectors.append(vec)

                    all_embeddings.extend(batch_vectors)
                    success = True
                    # Small throttle between batches to avoid instantaneous bursting
                    time.sleep(0.5)
                    break

                except Exception as exc:
                    wait_time = extract_retry_delay(exc, delay)
                    logger.warning(
                        f"Embedding attempt {attempt + 1}/{max_retries} encountered error / quota throttle: {exc}. "
                        f"Waiting {wait_time:.1f}s before retrying..."
                    )
                    time.sleep(wait_time)
                    delay = max(delay * 2, wait_time)
                    delay *= 2  # Exponential backoff

            if not success:
                raise RuntimeError(
                    f"Exhausted {max_retries} retries while embedding batch of {len(batch)} texts."
                )

        return all_embeddings
