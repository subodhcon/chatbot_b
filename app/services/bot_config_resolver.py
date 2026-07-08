import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("app.services.bot_config_resolver")


@dataclass
class BotConfigParams:
    """
    Resolved, safe-defaulted parameters extracted from a BotConfig row.
    Consumed by the AI response pipeline call sites in public.py and websocket.py.
    """
    system_prompt: Optional[str]
    tone: str
    welcome_message: Optional[str]
    fallback_message: Optional[str]
    model_name: str
    temperature: float
    max_tokens: int
    top_k: int
    similarity_threshold: float
    confidence_threshold: float


class BotConfigResolver:
    """
    Centralises the extraction and safe-defaulting of BotConfig fields
    required by the AI response pipeline.

    Design principles:
    - All BotConfig fields are optional at the DB level. This resolver applies
      sensible defaults so downstream services never receive None for required params.
    - confidence_threshold lives in BotConfig.extra_config (JSONB freeform bag).
      SQLite environments don't support JSONB — the resolver handles None gracefully.
    - Call sites should use resolver.resolve(config) rather than accessing
      BotConfig fields directly, eliminating duplicated null-handling logic.
    """

    # Defaults mirror BotConfig column-level defaults
    DEFAULT_TONE: str = "professional"
    DEFAULT_MODEL: str = "gpt-4o-mini"
    DEFAULT_TEMPERATURE: float = 0.7
    DEFAULT_MAX_TOKENS: int = 1024
    DEFAULT_TOP_K: int = 5
    DEFAULT_SIMILARITY_THRESHOLD: float = 0.45
    DEFAULT_CONFIDENCE_THRESHOLD: float = 0.40

    def resolve(self, config) -> BotConfigParams:
        """
        Extract and safe-default all pipeline parameters from a BotConfig ORM row.

        Args:
            config: A BotConfig SQLAlchemy model instance.

        Returns:
            BotConfigParams dataclass with all fields guaranteed non-None
            where a default makes sense.
        """
        # -- Tone --------------------------------------------------------
        tone = (config.tone or self.DEFAULT_TONE).strip().lower()

        # -- Model settings ----------------------------------------------
        model_name = config.model_name or self.DEFAULT_MODEL
        temperature = config.temperature if config.temperature is not None else self.DEFAULT_TEMPERATURE
        max_tokens = config.max_tokens if config.max_tokens is not None else self.DEFAULT_MAX_TOKENS

        # -- Retrieval settings ------------------------------------------
        top_k = config.top_k if config.top_k is not None else self.DEFAULT_TOP_K
        similarity_threshold = (
            config.similarity_threshold
            if config.similarity_threshold is not None
            else self.DEFAULT_SIMILARITY_THRESHOLD
        )

        # -- Confidence threshold (lives in extra_config JSONB bag) ------
        extra = config.extra_config or {}
        try:
            confidence_threshold = float(extra.get("confidence_threshold", self.DEFAULT_CONFIDENCE_THRESHOLD))
        except (TypeError, ValueError):
            logger.warning(
                "Invalid confidence_threshold in extra_config; using default %.1f",
                self.DEFAULT_CONFIDENCE_THRESHOLD,
            )
            confidence_threshold = self.DEFAULT_CONFIDENCE_THRESHOLD

        params = BotConfigParams(
            system_prompt=config.system_prompt or None,
            tone=tone,
            welcome_message=config.welcome_message or None,
            fallback_message=config.fallback_message or None,
            model_name=model_name,
            temperature=temperature,
            max_tokens=max_tokens,
            top_k=top_k,
            similarity_threshold=similarity_threshold,
            confidence_threshold=confidence_threshold,
        )

        logger.debug(
            "Resolved BotConfigParams: tone=%s, model=%s, top_k=%d, "
            "similarity_threshold=%.2f, confidence_threshold=%.2f, "
            "has_welcome=%s, has_fallback=%s, has_system_prompt=%s",
            params.tone,
            params.model_name,
            params.top_k,
            params.similarity_threshold,
            params.confidence_threshold,
            bool(params.welcome_message),
            bool(params.fallback_message),
            bool(params.system_prompt),
        )

        return params


# Module-level singleton
bot_config_resolver = BotConfigResolver()
