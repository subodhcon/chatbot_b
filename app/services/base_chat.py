from abc import ABC, abstractmethod
from typing import List, Dict, Any, AsyncGenerator


class BaseChatService(ABC):
    """
    Abstract base class establishing a provider-agnostic interface
    for Chat Services supporting completions and streaming.
    """

    @abstractmethod
    async def generate_response(
        self,
        system_prompt: str,
        user_prompt: str,
        chat_history: List[Dict[str, str]] = None,
        model_name: str = None,
        temperature: float = 0.7,
        max_tokens: int = 512,
    ) -> Dict[str, Any]:
        """
        Generates a non-streaming chat completion.
        Returns:
            Dict containing 'answer' (str) and 'metadata' (dict).
        """
        pass

    @abstractmethod
    async def generate_response_stream(
        self,
        system_prompt: str,
        user_prompt: str,
        chat_history: List[Dict[str, str]] = None,
        model_name: str = None,
        temperature: float = 0.7,
        max_tokens: int = 512,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Generates a streaming chat completion.
        Yields:
            Dict containing 'answer_chunk' (str) and optionally 'metadata' (dict).
        """
        pass
