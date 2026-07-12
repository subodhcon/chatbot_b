import logging
from typing import List, Dict, Any
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.knowledge_source import KnowledgeSource

logger = logging.getLogger("app.services.vector_search")


class VectorSearchService:
    """
    Service for performing semantic similarity searches using MongoDB vectorSearch.
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
        Retrieves top K similar text chunks for a bot using cosine similarity from MongoDB.
        Returns a list of dictionaries containing the chunk content, score, and source info.
        """
        if not query_vector:
            return []

        # Check if the bot has custom MongoDB enabled
        from app.models.bot_config import BotConfig
        import uuid
        
        bot_config_res = await db.execute(
            select(BotConfig).where(BotConfig.bot_id == bot_id)
        )
        bot_config = bot_config_res.scalars().first()

        # Check database parameters
        from app.core.config import settings
        from app.core.mongo import mongo_registry
        
        mongo_uri = None
        db_name = "chatbot"
        
        if bot_config and bot_config.use_custom_mongo and bot_config.mongo_uri:
            mongo_uri = bot_config.mongo_uri
            db_name = bot_config.mongo_db_name or "chatbot"
        elif settings.MONGODB_URL and "localhost" not in settings.MONGODB_URL:
            mongo_uri = settings.MONGODB_URL
            db_name = mongo_registry.get_database_name(settings.MONGODB_URL)
            
        if mongo_uri:
            mongo_client = mongo_registry.get_client(str(bot_id), mongo_uri)
            if mongo_client:
                mongo_db = mongo_client[db_name]
                chunks_collection = mongo_db["chunks"]
                
                pipeline = [
                    {
                        "$vectorSearch": {
                            "index": "vector_index",
                            "path": "embedding_vector",
                            "queryVector": query_vector,
                            "numCandidates": max(100, top_k * 10),
                            "limit": top_k
                        }
                    },
                    {
                        "$project": {
                            "_id": 1,
                            "source_id": 1,
                            "chunk_index": 1,
                            "content": 1,
                            "token_count": 1,
                            "score": {"$meta": "vectorSearchScore"}
                        }
                    }
                ]
                
                try:
                    cursor = chunks_collection.aggregate(pipeline)
                    mongo_results = []
                    async for doc in cursor:
                        mongo_results.append(doc)
                    
                    if not mongo_results:
                        return []
                    
                    # Fetch sources from MongoDB for joining source details
                    source_ids = [str(doc["source_id"]) for doc in mongo_results if "source_id" in doc]
                    sources_map = {}
                    if source_ids:
                        cursor_sources = mongo_db["knowledge_sources"].find({
                            "_id": {"$in": source_ids}
                        })
                        async for s_doc in cursor_sources:
                            s = KnowledgeSource(s_doc)
                            sources_map[str(s.id)] = s
                    
                    search_results = []
                    for doc in mongo_results:
                        score = float(doc.get("score", 0.0))
                        if score < min_score:
                            continue
                            
                        source = sources_map.get(doc.get("source_id"))
                        search_results.append({
                            "chunk": {
                                "id": doc["_id"],
                                "chunk_index": doc.get("chunk_index"),
                                "content": doc.get("content", ""),
                                "token_count": doc.get("token_count", 0),
                            },
                            "score": round(score, 4),
                            "source": {
                                "id": str(source.id) if source else doc.get("source_id"),
                                "source_name": source.source_name if source else "Unknown Source",
                                "source_type": source.source_type if source else "url",
                                "url": source.url if source else None,
                            }
                        })
                    return search_results
                except Exception as mongo_err:
                    logger.warning(f"MongoDB vector search failed, falling back to local python similarity search: {mongo_err}")
                    try:
                        # 1. Fetch all sources for this bot to map and filter chunks
                        cursor_sources = mongo_db["knowledge_sources"].find({"bot_id": str(bot_id)})
                        sources_map = {}
                        async for s_doc in cursor_sources:
                            s = KnowledgeSource(s_doc)
                            sources_map[str(s.id)] = s
                        
                        if not sources_map:
                            logger.info("Local similarity: No knowledge sources found for this bot.")
                            return []
                        
                        source_ids = list(sources_map.keys())
                        
                        # 2. Fetch all chunks matching these source IDs
                        cursor_chunks = chunks_collection.find({"source_id": {"$in": source_ids}})
                        all_chunks = []
                        async for ch in cursor_chunks:
                            all_chunks.append(ch)
                        
                        if not all_chunks:
                            logger.info("Local similarity: No chunks found in database.")
                            return []
                        
                        # 3. Calculate cosine similarity in Python
                        import math
                        def cosine_similarity(v1, v2):
                            if not v1 or not v2 or len(v1) != len(v2):
                                return 0.0
                            dot = sum(x * y for x, y in zip(v1, v2))
                            norm1 = math.sqrt(sum(x * x for x in v1))
                            norm2 = math.sqrt(sum(x * x for x in v2))
                            if norm1 == 0.0 or norm2 == 0.0:
                                return 0.0
                            return dot / (norm1 * norm2)
                        
                        scored_chunks = []
                        for ch in all_chunks:
                            emb = ch.get("embedding_vector")
                            if not emb:
                                continue
                            score = cosine_similarity(query_vector, emb)
                            scored_chunks.append((score, ch))
                        
                        scored_chunks.sort(key=lambda x: x[0], reverse=True)
                        
                        # Auto-adjust threshold: if no chunks pass the min_score, take the top match anyway
                        effective_min_score = min_score
                        if scored_chunks and scored_chunks[0][0] < min_score:
                            effective_min_score = scored_chunks[0][0] * 0.9 # loosen up to allow top matches
                            
                        top_chunks = [x for x in scored_chunks if x[0] >= effective_min_score][:top_k]
                        
                        search_results = []
                        for score, doc in top_chunks:
                            source = sources_map.get(str(doc.get("source_id")))
                            search_results.append({
                                "chunk": {
                                    "id": doc["_id"],
                                    "chunk_index": doc.get("chunk_index"),
                                    "content": doc.get("content", ""),
                                    "token_count": doc.get("token_count", 0),
                                },
                                "score": round(score, 4),
                                "source": {
                                    "id": str(source.id) if source else doc.get("source_id"),
                                    "source_name": source.source_name if source else "Unknown Source",
                                    "source_type": source.source_type if source else "url",
                                    "url": source.url if source else None,
                                }
                            })
                        return search_results
                    except Exception as fallback_err:
                        logger.error(f"Fallback local search also failed: {fallback_err}")
                        return []


        return []


# Module-level singleton
vector_search_service = VectorSearchService()
