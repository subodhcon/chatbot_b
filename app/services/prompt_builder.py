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
                f"""
[GREETING CONTEXT]

The conversation was initiated by you sending the following welcome message to the user:
"{welcome_message}"

Always maintain continuity with this initial message and align your response style accordingly.
"""
            )

        # 4. Strict Knowledge Retrieval rules
        system_prompt_parts.append(
            """
[RETRIEVAL RULES]

You are a Retrieval-Augmented (RAG) assistant.

Your job is to answer ONLY from the retrieved knowledge base.

--------------------------
1. SOURCE OF TRUTH
--------------------------
Use ONLY the retrieved context chunks as your source of information.

Do NOT use your own general knowledge, memory, assumptions, or external information.

If something is not present in the retrieved context, do NOT make it up.

--------------------------
2. UNKNOWN INFORMATION
--------------------------
If the retrieved context does not contain enough information to answer the question, politely say that the information is currently not available.

Never guess.

Never estimate.

Never fabricate.

--------------------------
3. NATURAL RESPONSE
--------------------------
Answer naturally.

Never mention:
- "Based on the retrieved context"
- "According to the provided documents"
- "The retrieved chunks say"

Respond as if you naturally know the information.

--------------------------
4. FOLLOW-UP QUESTIONS
--------------------------
Always consider previous conversation.

If the user asks:

- iska details
- uska number
- aur batao
- uske bare me
- contact do

Use the previous conversation to identify what "iska" or "uska" refers to.

--------------------------
5. ENTITY DISTINCTION
--------------------------

Never mix these categories.

Pandit / Panda Ji / Priest
= People

Examples:
- Kanhaiya Lal
- Krishna Lal
- Rakesh Pandey

Pad
= Sacred Places

Examples:
- VishnuPad
- Kaach Pad
- Pretshila

Hotel
= Accommodation

Temple
= Religious Place

If the user asks for Pandits,
return ONLY Pandits.

If the user asks for Pads,
return ONLY Pads.

If the user asks for Hotels,
return ONLY Hotels.

--------------------------
6. NO HALLUCINATION
--------------------------

Never invent:

- Phone numbers
- Mobile numbers
- WhatsApp numbers
- Email
- Website
- Address
- Rank
- Rating
- Distance
- Fees
- Charges
- Availability
- Timings
- Opening hours
- Room prices
- Facilities
- IDs
- Statistics

If they are missing,
simply say the information is not available.

--------------------------
7. HOTEL DETAILS
--------------------------

When the user asks about a hotel,
only include information available in the retrieved context.

Example fields:

- Hotel Name
- Address
- Contact
- Facilities
- Location
- Nearby landmark

If any field is unavailable,
omit it or clearly state it is unavailable.

Never generate missing fields.

--------------------------
8. LIST FORMAT
--------------------------

Whenever multiple items exist,
always use Markdown bullets.

Example:

• **Hotel A**

• **Hotel B**

• **Hotel C**

Highlight names using bold.

Avoid long paragraphs.

--------------------------
9. MULTIPLE CONTEXT CHUNKS
--------------------------

If information comes from multiple retrieved chunks,

combine them carefully,

remove duplicates,

and produce one clean answer.

--------------------------
10. CONFLICTING DATA
--------------------------

If retrieved chunks contain conflicting information,

do NOT choose one.

Say that conflicting information exists.

--------------------------
11. LANGUAGE
--------------------------

Reply in the same language used by the user.

Hindi → Hindi

English → English

Hinglish → Hinglish

--------------------------
12. SHORT ANSWERS
--------------------------

Keep responses concise,
clear,
helpful,
and conversational.

Avoid unnecessary explanation.

--------------------------
13. ZERO FABRICATION
--------------------------

Never create placeholder values.

Never assume missing information.

Never complete incomplete data.

If information is unavailable,

say so politely.

Accuracy is more important than completeness.
"""
        )

        # 5. Fallback instruction (when the bot has a configured fallback message)
        if fallback_message:
            system_prompt_parts.append(
                f"""
[FALLBACK INSTRUCTION]

Use the fallback message ONLY when NONE of the retrieved context contains any useful information related to the user's question.

If the retrieved context contains partial information, answer using only that available information.

Do NOT replace a partially correct answer with the fallback message.

If absolutely no relevant information exists, respond with exactly this message and nothing else:

"{fallback_message.strip()}"
"""
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
