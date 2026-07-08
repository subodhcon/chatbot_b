import time
import logging
from typing import List
from openai import OpenAI, OpenAIError
from app.core.config import settings

logger = logging.getLogger("app.services.openai_embeddings")


import os

# Fallback Gemini key to use for embeddings when client is using Groq
GEMINI_FALLBACK_KEY = settings.GEMINI_API_KEY


class OpenAIEmbeddingService:
    """
    Service for generating vector embeddings using the OpenAI API.
    Includes batch processing, robust error handling, and auto-retry logic with exponential backoff.
    """

    def __init__(self, api_key: str = settings.OPENAI_API_KEY, model: str = "text-embedding-3-small") -> None:
        self.api_key = api_key
        self.model = model
        self._client = None

    @property
    def client(self) -> OpenAI:
        if not self._client:
            if not self.api_key:
                raise ValueError("OpenAI API Key is missing. Please configure it in your settings/.env file.")
            if self.api_key.startswith("gsk_"):
                # Groq has no embeddings, we don't instantiate OpenAI client with Groq key
                raise ValueError("Groq does not support embeddings. Embedding generation falls back to Gemini API.")
            self._client = OpenAI(api_key=self.api_key)
        return self._client

    def generate_embedding(self, text: str, max_retries: int = 3, backoff_factor: float = 2.0) -> List[float]:
        """
        Generates a single embedding vector for the input text.
        Includes automatic retry support on API rate limits or transient server failures.
        """
        if not text:
            return []

        results = self.generate_embeddings_batch([text], max_retries=max_retries, backoff_factor=backoff_factor)
        return results[0] if results else []

    def generate_embeddings_batch(self, texts: List[str], max_retries: int = 3, backoff_factor: float = 2.0) -> List[List[float]]:
        """
        Generates embeddings for a batch of text strings in a single API call.
        Handles API errors, rate limits, and applies exponential backoff retries.
        Supports both OpenAI and Google Gemini keys.
        """
        cleaned_texts = [t.strip() for t in texts if t and t.strip()]
        if not cleaned_texts:
            return []

        api_key_to_use = self.api_key
        # Detect if Groq key is used and fallback to Gemini
        if api_key_to_use.startswith("gsk_"):
            api_key_to_use = GEMINI_FALLBACK_KEY

        # Check if the key is a Google Gemini API Key
        if api_key_to_use.startswith("AIzaSy") or api_key_to_use.startswith("AQ."):
            import httpx
            requests_payload = []
            for t in cleaned_texts:
                requests_payload.append({
                    "model": "models/gemini-embedding-001",
                    "content": {
                        "parts": [{"text": t}]
                    },
                    "outputDimensionality": 1536
                })

            delay = 1.0  # Initial retry delay in seconds
            for attempt in range(max_retries + 1):
                try:
                    logger.info(f"Sending batch of {len(cleaned_texts)} texts to Gemini Embedding API (Attempt {attempt + 1}/{max_retries + 1})")
                    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-embedding-001:batchEmbedContents?key={api_key_to_use}"
                    with httpx.Client() as client:
                        resp = client.post(
                            url,
                            json={"requests": requests_payload},
                            headers={"Content-Type": "application/json"},
                            timeout=15.0
                        )
                        if resp.status_code == 200:
                            resp_data = resp.json()
                            embeddings_list = resp_data.get("embeddings", [])
                            return [emb["values"] for emb in embeddings_list]
                        else:
                            raise ValueError(f"Gemini API error: {resp.status_code} - {resp.text}")
                except Exception as e:
                    if attempt < max_retries:
                        logger.warning(
                            f"Gemini Embedding API error encountered. "
                            f"Retrying in {delay:.2f} seconds... Error: {e}"
                        )
                        time.sleep(delay)
                        delay *= backoff_factor
                    else:
                        logger.error(f"Failed to generate Gemini embeddings after {max_retries + 1} attempts. Error: {e}", exc_info=True)
                        raise ValueError(f"Gemini Embedding API call failed: {str(e)}") from e

        # Fallback to OpenAI call
        delay = 1.0  # Initial retry delay in seconds
        for attempt in range(max_retries + 1):
            try:
                logger.info(f"Sending batch of {len(cleaned_texts)} texts to OpenAI Embedding API (Attempt {attempt + 1}/{max_retries + 1})")
                response = self.client.embeddings.create(
                    input=cleaned_texts,
                    model=self.model,
                )
                return [data.embedding for data in response.data]

            except OpenAIError as e:
                # Handle rate limit (429) or transient errors (500, 503)
                is_rate_limit = getattr(e, "status_code", None) == 429
                is_server_error = getattr(e, "status_code", None) in (500, 502, 503, 504)
                
                if attempt < max_retries and (is_rate_limit or is_server_error):
                    logger.warning(
                        f"OpenAI API rate limit or server error encountered (Status: {getattr(e, 'status_code', None)}). "
                        f"Retrying in {delay:.2f} seconds... Error: {e}"
                    )
                    time.sleep(delay)
                    delay *= backoff_factor
                else:
                    logger.error(f"Failed to generate embeddings after {max_retries + 1} attempts. Error: {e}", exc_info=True)
                    raise ValueError(f"OpenAI Embedding API call failed: {str(e)}") from e

            except Exception as e:
                logger.error(f"Unexpected error calling OpenAI Embedding API: {e}", exc_info=True)
                raise ValueError(f"Unexpected embedding error: {str(e)}") from e


# Module-level singleton
openai_embedding_service = OpenAIEmbeddingService()
