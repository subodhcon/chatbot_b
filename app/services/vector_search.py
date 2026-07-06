import logging
from typing import List, Dict, Any
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.embedding import Embedding
from app.models.source_chunk import SourceChunk
from app.models.knowledge_source import KnowledgeSource

logger = logging.getLogger("app.services.vector_search")


class VectorSearchService:
    """
    Service for performing semantic similarity searches using pgvector cosine distance.
    """

    async def search_similar_chunks(
        self,
        db: AsyncSession,
        *,
        bot_id: Any,
        query_vector: List[float],
        top_k: int = 5,
        min_score: float = 0.0,
    ) -> List[Dict[str, Any]]:
        """
        Retrieves top K similar text chunks for a bot using cosine similarity.
        Returns a list of dictionaries containing the chunk content, score, and source info.
        """
        if not query_vector:
            return []

        # Cosine distance from query vector
        distance_col = Embedding.embedding_vector.cosine_distance(query_vector)

        # Select columns, join tables, filter by bot_id, and order by distance ascending
        query = (
            select(SourceChunk, KnowledgeSource, distance_col)
            .join(SourceChunk, Embedding.chunk_id == SourceChunk.id)
            .join(KnowledgeSource, SourceChunk.source_id == KnowledgeSource.id)
            .where(KnowledgeSource.bot_id == bot_id)
            .order_by(distance_col)
            .limit(top_k)
        )

        try:
            result = await db.execute(query)
            rows = result.all()

            search_results = []
            for chunk, source, distance in rows:
                # Cosine similarity score = 1 - cosine_distance
                score = 1.0 - float(distance) if distance is not None else 0.0

                # Filter by minimum similarity score if threshold is provided
                if score < min_score:
                    continue

                search_results.append({
                    "chunk": {
                        "id": str(chunk.id),
                        "chunk_index": chunk.chunk_index,
                        "content": chunk.content,
                        "token_count": chunk.token_count,
                    },
                    "score": round(score, 4),
                    "source": {
                        "id": str(source.id),
                        "source_name": source.source_name,
                        "source_type": source.source_type,
                        "url": source.url,
                    }
                })

            return search_results

        except Exception as e:
            logger.error(f"Failed to perform vector similarity search for bot {bot_id}: {e}", exc_info=True)
            raise ValueError(f"Vector search failed: {str(e)}") from e


# Module-level singleton
vector_search_service = VectorSearchService()
