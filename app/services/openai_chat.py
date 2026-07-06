import asyncio
import logging
from typing import List, Dict, Any, AsyncGenerator
from openai import AsyncOpenAI, OpenAIError
from app.core.config import settings
from app.services.base_chat import BaseChatService

logger = logging.getLogger("app.services.openai_chat")


class OpenAIChatService(BaseChatService):
    """
    OpenAI Chat Completion Service implementing BaseChatService.
    Supports streaming, custom model configuration, and automatic retry handling.
    """

    def __init__(self, api_key: str = settings.OPENAI_API_KEY, default_model: str = "gpt-4o-mini") -> None:
        self.api_key = api_key
        self.default_model = default_model
        self._client = None

    @property
    def client(self) -> AsyncOpenAI:
        if not self._client:
            if not self.api_key:
                raise ValueError("OpenAI API Key is missing. Please configure it in your settings/.env file.")
            self._client = AsyncOpenAI(api_key=self.api_key)
        return self._client

    async def _execute_with_retry(self, func, max_retries: int = 3, backoff_factor: float = 2.0, *args, **kwargs):
        """
        Executes a coroutine function with retry logic and exponential backoff.
        """
        delay = 1.0
        for attempt in range(max_retries + 1):
            try:
                return await func(*args, **kwargs)
            except OpenAIError as e:
                is_rate_limit = getattr(e, "status_code", None) == 429
                is_server_error = getattr(e, "status_code", None) in (500, 502, 503, 504)

                if attempt < max_retries and (is_rate_limit or is_server_error):
                    logger.warning(
                        f"OpenAI Chat API transient error (Status: {getattr(e, 'status_code', None)}). "
                        f"Retrying in {delay:.2f} seconds... Error: {e}"
                    )
                    await asyncio.sleep(delay)
                    delay *= backoff_factor
                else:
                    logger.error(f"OpenAI Chat API call failed after {max_retries + 1} attempts: {e}", exc_info=True)
                    raise ValueError(f"OpenAI API call failed: {str(e)}") from e
            except Exception as e:
                logger.error(f"Unexpected error in OpenAI Chat Service: {e}", exc_info=True)
                raise ValueError(f"Chat service error: {str(e)}") from e

    async def generate_response(
        self,
        system_prompt: str,
        user_prompt: str,
        chat_history: List[Dict[str, str]] = None,
        model_name: str = None,
        temperature: float = 0.7,
        max_tokens: int = 512,
        max_retries: int = 3,
        backoff_factor: float = 2.0,
    ) -> Dict[str, Any]:
        """
        Generates a non-streaming chat response.
        Returns:
            Dict containing 'answer' (str) and 'metadata' (dict).
        """
        # Route to Gemini if key starts with AIzaSy or AQ.
        if self.api_key.startswith("AIzaSy") or self.api_key.startswith("AQ."):
            import httpx
            gemini_contents = []
            if chat_history:
                for h in chat_history:
                    role = "user" if h["role"] == "user" else "model"
                    gemini_contents.append({
                        "role": role,
                        "parts": [{"text": h["content"]}]
                    })
            gemini_contents.append({
                "role": "user",
                "parts": [{"text": user_prompt}]
            })
            
            system_instructions = system_prompt or "You are a helpful assistant."
            
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={self.api_key}",
                    headers={"Content-Type": "application/json"},
                    json={
                        "contents": gemini_contents,
                        "systemInstruction": {
                            "parts": [{"text": system_instructions}]
                        },
                        "generationConfig": {
                            "temperature": temperature,
                            "maxOutputTokens": max_tokens
                        }
                    },
                    timeout=15.0
                )
                if resp.status_code == 200:
                    resp_json = resp.json()
                    answer = resp_json["candidates"][0]["content"]["parts"][0]["text"] or ""
                    return {
                        "answer": answer.strip(),
                        "metadata": {
                            "model": "gemini-2.5-flash",
                            "usage": {
                                "prompt_tokens": None,
                                "completion_tokens": None,
                                "total_tokens": None,
                            },
                            "finish_reason": "stop"
                        }
                    }
                else:
                    raise ValueError(f"Gemini API error: {resp.status_code} - {resp.text}")

        model = model_name or self.default_model
        messages = [{"role": "system", "content": system_prompt}]

        if chat_history:
            for message in chat_history:
                messages.append({"role": message["role"], "content": message["content"]})

        messages.append({"role": "user", "content": user_prompt})

        async def _call_api():
            return await self.client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )

        response = await self._execute_with_retry(_call_api, max_retries, backoff_factor)

        answer = response.choices[0].message.content or ""
        metadata = {
            "model": model,
            "usage": {
                "prompt_tokens": response.usage.prompt_tokens if response.usage else None,
                "completion_tokens": response.usage.completion_tokens if response.usage else None,
                "total_tokens": response.usage.total_tokens if response.usage else None,
            },
            "finish_reason": response.choices[0].finish_reason,
        }

        return {
            "answer": answer.strip(),
            "metadata": metadata,
        }

    async def generate_response_stream(
        self,
        system_prompt: str,
        user_prompt: str,
        chat_history: List[Dict[str, str]] = None,
        model_name: str = None,
        temperature: float = 0.7,
        max_tokens: int = 512,
        max_retries: int = 3,
        backoff_factor: float = 2.0,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Generates a streaming chat response yielding chunks containing token/delta updates
        and final metadata.
        """
        # Route to Gemini if key starts with AIzaSy or AQ.
        if self.api_key.startswith("AIzaSy") or self.api_key.startswith("AQ."):
            import httpx
            import json
            gemini_contents = []
            if chat_history:
                for h in chat_history:
                    role = "user" if h["role"] == "user" else "model"
                    gemini_contents.append({
                        "role": role,
                        "parts": [{"text": h["content"]}]
                    })
            gemini_contents.append({
                "role": "user",
                "parts": [{"text": user_prompt}]
            })
            
            system_instructions = system_prompt or "You are a helpful assistant."
            
            async with httpx.AsyncClient() as client:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:streamGenerateContent?key={self.api_key}"
                async with client.stream(
                    "POST",
                    url,
                    headers={"Content-Type": "application/json"},
                    json={
                        "contents": gemini_contents,
                        "systemInstruction": {
                            "parts": [{"text": system_instructions}]
                        },
                        "generationConfig": {
                            "temperature": temperature,
                            "maxOutputTokens": max_tokens
                        }
                    },
                    timeout=15.0
                ) as response:
                    if response.status_code != 200:
                        body = await response.aread()
                        raise ValueError(f"Gemini Stream API error: {response.status_code} - {body.decode()}")
                    
                    buffer = ""
                    async for chunk in response.aiter_bytes():
                        buffer += chunk.decode("utf-8")
                        braces = 0
                        start = -1
                        for idx, char in enumerate(buffer):
                            if char == '{':
                                if braces == 0:
                                    start = idx
                                braces += 1
                            elif char == '}':
                                braces -= 1
                                if braces == 0 and start != -1:
                                    obj_str = buffer[start:idx+1]
                                    try:
                                        obj = json.loads(obj_str)
                                        text_part = obj["candidates"][0]["content"]["parts"][0]["text"]
                                        if text_part:
                                            yield {
                                                "answer_chunk": text_part,
                                                "metadata": {
                                                    "model": "gemini-2.5-flash",
                                                    "finish_reason": "stop"
                                                }
                                            }
                                    except Exception:
                                        pass
                                    buffer = buffer[idx+1:]
            return

        model = model_name or self.default_model
        messages = [{"role": "system", "content": system_prompt}]

        if chat_history:
            for message in chat_history:
                messages.append({"role": message["role"], "content": message["content"]})

        messages.append({"role": "user", "content": user_prompt})

        async def _call_api_stream():
            return await self.client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=True,
            )

        stream = await self._execute_with_retry(_call_api_stream, max_retries, backoff_factor)

        async for chunk in stream:
            delta = chunk.choices[0].delta if chunk.choices else None
            content = delta.content if delta else None
            if content:
                yield {
                    "answer_chunk": content,
                    "metadata": {
                        "model": model,
                        "finish_reason": chunk.choices[0].finish_reason if chunk.choices else None,
                    }
                }


# Module-level singleton
openai_chat_service = OpenAIChatService()
