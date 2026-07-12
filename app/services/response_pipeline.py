import logging
from typing import List, Dict, Any, AsyncGenerator, Union
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.openai_embeddings import openai_embedding_service
from app.services.vector_search import vector_search_service
from app.services.citation_mapper import citation_mapping_service
from app.services.prompt_builder import prompt_builder_service
from app.services.openai_chat import openai_chat_service
from app.services.confidence_score import confidence_score_service
from app.services.fallback import fallback_response_service

logger = logging.getLogger("app.services.response_pipeline")


class AIResponsePipelineService:
    """
    Orchestrates the retrieval-augmented generation (RAG) pipeline:
    1. Query embedding generation
    2. Vector database search
    3. Context preparation & citation mapping
    4. Prompt construction
    5. OpenAI Chat Completion (standard or streaming)
    6. Citation resolution & metadata attachment
    """
    
    async def _condense_query(
        self,
        user_question: str,
        chat_history: List[Dict[str, str]] = None,
        model_name: str = "gpt-4o-mini"
    ) -> str:
        if not chat_history or len(chat_history) == 0:
            return user_question

        # Format recent chat history for the condensation prompt
        history_str = ""
        for msg in chat_history[-5:]:
            role = "User" if msg.get("role") == "user" else "Assistant"
            content = msg.get("content", "")
            history_str += f"{role}: {content}\n"

        prompt = f"""You are a query rewriting assistant. Given the conversation history and a follow-up question, rewrite the follow-up question into a standalone, descriptive search query.

CRITICAL INSTRUCTIONS:
1. Pronoun Resolution: Replace pronouns (e.g., "iska", "uska", "it", "they", "this", "that", "him", "her") with the exact entity name (e.g., Hotel Name, Priest Name, Place Name) mentioned in the conversation history.
2. Search Intent Retention: Ensure the query preserves the user's search intent (e.g., if they ask for "number", make it "contact number of [Entity]").
3. Remove Conversational Fillers: Exclude polite phrases (e.g., "please", "thank you", "okay") or questions directed to the bot.
4. Original Language: Write the standalone query in the original language used by the user (Hindi, English, or Hinglish).
5. Do NOT answer the question. Only output the rewritten standalone query and nothing else.

Conversation History:
{history_str}
Follow-up Question: {user_question}

Standalone Query:"""

        try:
            res = await openai_chat_service.generate_response(
                system_prompt="You are a query rewriting assistant. Rewrite the user's follow-up question into a standalone, descriptive search query.",
                user_prompt=prompt,
                chat_history=None,
                model_name=model_name,
                temperature=0.0,
                max_tokens=64,
            )
            condensed = res.get("answer", "").strip()
            if condensed:
                logger.info(f"[Condensation] Rewrote '{user_question}' -> '{condensed}'")
                return condensed
        except Exception as e:
            logger.warning(f"[Condensation] Failed to condense query: {e}. Falling back to raw question.")
            
        return user_question

    async def generate_response(
        self,
        db: AsyncSession,
        *,
        bot_id: Any,
        user_question: str,
        chat_history: List[Dict[str, str]] = None,
        # Config parameters override or defaults
        system_prompt: str = None,
        tone: str = "professional",
        welcome_message: str = None,
        fallback_message: str = None,
        model_name: str = "gpt-4o-mini",
        temperature: float = 0.7,
        max_tokens: int = 512,
        top_k: int = 5,
        similarity_threshold: float = 0.0,
        confidence_threshold: float = 0.0,
    ) -> Dict[str, Any]:
        """
        Executes the full non-streaming response pipeline.
        Returns:
            Dict containing:
            - 'answer': Cleaned LLM answer (str)
            - 'citations': List of unique sources cited (list)
            - 'metadata': Metrics/execution logs of the request (dict)
        """
        try:
            # Step 1: Embedding generation
            logger.info(f"Generating query embedding for bot {bot_id}...")
            condensed_question = await self._condense_query(user_question, chat_history, model_name=model_name)
            query_vector = openai_embedding_service.generate_embedding(condensed_question)

            # Step 2: Vector Search
            logger.info(f"Performing vector similarity search (top_k={top_k}, similarity_threshold={similarity_threshold})...")
            retrieved_chunks = await vector_search_service.search_similar_chunks(
                db=db,
                bot_id=bot_id,
                query_vector=query_vector,
                top_k=top_k,
                min_score=similarity_threshold,
            )

            # Step 3: Citation decoration
            decorated_chunks, context_str = citation_mapping_service.format_chunks(retrieved_chunks)

            # Step 4: Prompt Construction
            prompts = prompt_builder_service.build_prompt(
                user_question=user_question,
                retrieved_chunks=decorated_chunks,
                base_system_prompt=system_prompt,
                tone=tone,
                welcome_message=welcome_message,
                fallback_message=fallback_message,
            )

            # Step 5: Chat Completion
            logger.info(f"Invoking OpenAI Chat Completion using model={model_name}...")
            chat_result = await openai_chat_service.generate_response(
                system_prompt=prompts["system_prompt"],
                user_prompt=prompts["user_prompt"],
                chat_history=chat_history,
                model_name=model_name,
                temperature=temperature,
                max_tokens=max_tokens,
            )

            # Step 6: Citation mapping resolution
            citation_result = citation_mapping_service.extract_citations(
                answer=chat_result["answer"],
                formatted_chunks=decorated_chunks,
            )

            # Step 7: Confidence calculation
            confidence_metrics = confidence_score_service.calculate_confidence(
                retrieved_chunks=retrieved_chunks,
                answer=citation_result["clean_answer"],
                fallback_message=fallback_message,
            )

            # Step 8: Fallback response system execution
            fallback_res = fallback_response_service.process_fallback(
                user_question=user_question,
                generated_answer=citation_result["clean_answer"],
                confidence_metrics=confidence_metrics,
                confidence_threshold=confidence_threshold,
                fallback_message=fallback_message,
            )

            return {
                "answer": fallback_res["answer"],
                "citations": citation_result["citations"],
                "escalation_eligible": fallback_res["escalation_eligible"],
                "metadata": {
                    **chat_result["metadata"],
                    "retrieved_chunks_count": len(retrieved_chunks),
                    "cited_sources_count": len(citation_result["citations"]),
                    "confidence_score": confidence_metrics["combined_confidence"],
                    "retrieval_confidence": confidence_metrics["retrieval_confidence"],
                    "answer_confidence": confidence_metrics["answer_confidence"],
                    "is_low_confidence": confidence_metrics["combined_confidence"] < confidence_threshold,
                    "escalation_eligible": fallback_res["escalation_eligible"],
                }
            }

        except Exception as e:
            logger.error(f"AI Response Pipeline failed for bot {bot_id}: {e}", exc_info=True)
            raise ValueError(f"AI response pipeline failure: {str(e)}") from e

    async def generate_response_stream(
        self,
        db: AsyncSession,
        *,
        bot_id: Any,
        user_question: str,
        chat_history: List[Dict[str, str]] = None,
        # Config parameters override or defaults
        system_prompt: str = None,
        tone: str = "professional",
        welcome_message: str = None,
        fallback_message: str = None,
        model_name: str = "gpt-4o-mini",
        temperature: float = 0.7,
        max_tokens: int = 512,
        top_k: int = 5,
        similarity_threshold: float = 0.0,
        confidence_threshold: float = 0.0,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Executes the streaming response pipeline.
        Yields:
            Dict elements of two types:
            - Content chunks: {"answer_chunk": str}
            - Final mapping resolution (yielded last): {"answer": str, "citations": list, "metadata": dict}
        """
        try:
            # Step 1: Embedding generation
            condensed_question = await self._condense_query(user_question, chat_history, model_name=model_name)
            query_vector = openai_embedding_service.generate_embedding(condensed_question)

            # Step 2: Vector Search
            retrieved_chunks = await vector_search_service.search_similar_chunks(
                db=db,
                bot_id=bot_id,
                query_vector=query_vector,
                top_k=top_k,
                min_score=similarity_threshold,
            )

            # Step 3: Citation decoration
            decorated_chunks, context_str = citation_mapping_service.format_chunks(retrieved_chunks)

            # Step 4: Prompt Construction
            prompts = prompt_builder_service.build_prompt(
                user_question=user_question,
                retrieved_chunks=decorated_chunks,
                base_system_prompt=system_prompt,
                tone=tone,
                welcome_message=welcome_message,
                fallback_message=fallback_message,
            )

            # Step 5: Streaming Chat Completion
            accumulated_answer_parts = []
            final_metadata = {"model": model_name}

            async for chunk in openai_chat_service.generate_response_stream(
                system_prompt=prompts["system_prompt"],
                user_prompt=prompts["user_prompt"],
                chat_history=chat_history,
                model_name=model_name,
                temperature=temperature,
                max_tokens=max_tokens,
            ):
                chunk_text = chunk.get("answer_chunk") or ""
                accumulated_answer_parts.append(chunk_text)
                if chunk.get("metadata"):
                    final_metadata.update(chunk["metadata"])

                yield {"answer_chunk": chunk_text}

            # Step 6: Citation mapping resolution
            full_answer = "".join(accumulated_answer_parts)
            citation_result = citation_mapping_service.extract_citations(
                answer=full_answer,
                formatted_chunks=decorated_chunks,
            )

            # Step 7: Confidence calculation
            confidence_metrics = confidence_score_service.calculate_confidence(
                retrieved_chunks=retrieved_chunks,
                answer=citation_result["clean_answer"],
                fallback_message=fallback_message,
            )

            # Step 8: Fallback response system execution
            fallback_res = fallback_response_service.process_fallback(
                user_question=user_question,
                generated_answer=citation_result["clean_answer"],
                confidence_metrics=confidence_metrics,
                confidence_threshold=confidence_threshold,
                fallback_message=fallback_message,
            )

            yield {
                "answer": fallback_res["answer"],
                "citations": citation_result["citations"],
                "escalation_eligible": fallback_res["escalation_eligible"],
                "metadata": {
                    **final_metadata,
                    "retrieved_chunks_count": len(retrieved_chunks),
                    "cited_sources_count": len(citation_result["citations"]),
                    "confidence_score": confidence_metrics["combined_confidence"],
                    "retrieval_confidence": confidence_metrics["retrieval_confidence"],
                    "answer_confidence": confidence_metrics["answer_confidence"],
                    "is_low_confidence": confidence_metrics["combined_confidence"] < confidence_threshold,
                    "escalation_eligible": fallback_res["escalation_eligible"],
                }
            }

        except Exception as e:
            logger.error(f"AI Streaming Response Pipeline failed for bot {bot_id}: {e}", exc_info=True)
            raise ValueError(f"AI response streaming pipeline failure: {str(e)}") from e


# Module-level singleton
ai_response_pipeline_service = AIResponsePipelineService()
