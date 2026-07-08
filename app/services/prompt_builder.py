import logging
from typing import List, Dict, Any, Union

logger = logging.getLogger("app.services.prompt_builder")


class PromptBuilderService:
    """
    Service for dynamically building LLM-provider-independent system and user prompts
    by combining user questions, retrieved knowledge base chunks, bot tones,
    and bot greeting context (welcome message).
    """

    def build_system_prompt(
        self,
        base_system_prompt: str,
        tone: str,
        welcome_message: str,
        fallback_message: str = None,
    ) -> str:
        """
        Builds the system instruction prompt configuring persona, tone,
        greeting context, fallback instruction, and retrieval rules.
        """
        system_prompt_parts = []

        # 1. Base system prompt (Persona / Instructions)
        if base_system_prompt:
            system_prompt_parts.append(base_system_prompt.strip())
        else:
            system_prompt_parts.append("You are a helpful and intelligent AI assistant.")

        # 2. Conversational tone constraint
        tone_lower = (tone or "professional").lower().strip()
        tone_guidelines = {
            "friendly": "Keep your tone friendly, warm, empathetic, and enthusiastic. Use positive words and occasional friendly emojis where appropriate.",
            "casual": "Keep your tone casual, relaxed, and conversational. Use simple language and speak like a close peer, keeping it informal yet helpful.",
            "formal": "Keep your tone formal, polite, objective, and precise. Avoid slang, contractions, and emojis; maintain high professionalism.",
            "professional": "Keep your tone professional, clear, respectful, and authoritative. Provide direct, helpful, and well-structured responses."
        }
        tone_instruction = tone_guidelines.get(tone_lower, tone_guidelines["professional"])
        system_prompt_parts.append(f"\n[TONE & STYLE GUIDELINE]\n{tone_instruction}")

        # 3. Greeting Context / Welcome message reference
        if welcome_message:
            system_prompt_parts.append(
                f"\n[GREETING CONTEXT]\n"
                f"The conversation was initiated by you sending the following welcome message to the user:\n"
                f"\"{welcome_message.strip()}\"\n"
                f"Always maintain continuity with this initial message and align your response style accordingly."
            )

        # 4. Strict Knowledge Retrieval rules
        system_prompt_parts.append(
            "\n[RETRIEVAL RULES]\n"
            "1. You will be provided with context chunks retrieved from the knowledge base.\n"
            "2. Answer the user's question using ONLY the provided context chunks.\n"
            "3. If the context does not contain the answer, or if there is no context provided, state clearly that you cannot answer based on the available information, or follow the fallback instruction (if provided).\n"
            "4. Maintain a natural conversation. Do NOT explicitly say 'Based on the provided context' or 'According to the retrieved chunks' or similar phrases. Answer as if you naturally know the information.\n"
            "5. Keep responses concise, conversational, and highly readable. Avoid writing long essays or massive paragraphs. Use clean bullet points for lists and bold highlights for readability. Try to keep the final answer under 3-4 sentences unless a detailed explanation is explicitly requested."
        )

        # 5. Fallback instruction (when the bot has a configured fallback message)
        if fallback_message:
            system_prompt_parts.append(
                f"\n[FALLBACK INSTRUCTION]\n"
                f"If you cannot answer the user's question using the provided knowledge context, "
                f"respond with exactly the following message and nothing else:\n"
                f"\"{fallback_message.strip()}\""
            )

        return "\n".join(system_prompt_parts)

    def build_user_prompt(
        self,
        user_question: str,
        retrieved_chunks: List[Union[str, Dict[str, Any]]],
    ) -> str:
        """
        Builds the user prompt combining the context chunks and the user's question.
        """
        # Format the retrieved chunks
        formatted_chunks = []
        if retrieved_chunks:
            for idx, chunk in enumerate(retrieved_chunks):
                if isinstance(chunk, dict):
                    content = chunk.get("content") or chunk.get("chunk", {}).get("content", "")
                    source_name = chunk.get("source", {}).get("source_name", "Unknown Source")
                else:
                    content = str(chunk)
                    source_name = f"Document Section {idx + 1}"

                if content:
                    formatted_chunks.append(
                        f"--- CONTEXT BLOCK {idx + 1} (Source: {source_name}) ---\n"
                        f"{content.strip()}"
                    )

        context_str = "\n\n".join(formatted_chunks) if formatted_chunks else "No relevant context found."

        user_prompt = (
            f"[KNOWLEDGE CONTEXT]\n"
            f"{context_str}\n\n"
            f"[USER QUESTION]\n"
            f"{user_question.strip()}\n\n"
            f"Please respond to the user question using the knowledge context above following the system rules.\n"
            f"CRITICAL: Keep your response short and very concise (maximum 2-3 sentences). Answer directly. Do NOT include large tech-stack bullet lists or detailed contact lists unless explicitly requested by the user."
        )
        return user_prompt

    def build_prompt(
        self,
        user_question: str,
        retrieved_chunks: List[Union[str, Dict[str, Any]]],
        base_system_prompt: str,
        tone: str,
        welcome_message: str,
        fallback_message: str = None,
    ) -> Dict[str, str]:
        """
        Generates a provider-independent structured prompt configuration.
        Returns a dictionary containing 'system_prompt' and 'user_prompt'.
        """
        return {
            "system_prompt": self.build_system_prompt(
                base_system_prompt, tone, welcome_message, fallback_message
            ),
            "user_prompt": self.build_user_prompt(user_question, retrieved_chunks)
        }


# Module-level singleton
prompt_builder_service = PromptBuilderService()
