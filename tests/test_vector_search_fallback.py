import pytest
from unittest.mock import MagicMock, AsyncMock
from app.services.vector_search import vector_search_service
from app.services.openai_embeddings import openai_embedding_service

@pytest.mark.asyncio
async def test_vector_search_fallback_local_search():
    """
    Test Phase 1: Local similarity search fallback using min-heap streaming and safety cap.
    """
    # 1. Mock DB Session and BotConfig
    db_mock = AsyncMock()
    
    # Mock bot config query result
    mock_execute_res = MagicMock()
    mock_execute_res.scalars.return_value.first.return_value = MagicMock(
        use_custom_mongo=False,
        mongo_uri=None
    )
    db_mock.execute.return_value = mock_execute_res

    # Mock active model name from embedding service
    orig_get_active_model_name = openai_embedding_service.get_active_model_name
    openai_embedding_service.get_active_model_name = MagicMock(return_value="text-embedding-3-small")

    # 2. Mock MongoDB client, database, and collections
    # We will trigger the fallback path by making the initial MongoDB vectorSearch aggregate query raise an Exception
    # (simulating non-Atlas environment or indexing failure)
    
    mock_chunks_collection = MagicMock()
    # aggregate raises exception to trigger fallback
    mock_chunks_collection.aggregate.side_effect = Exception("Vector search index not found")
    
    # Mock cursor for find
    mock_chunks_cursor = AsyncMock()
    mock_chunks = [
        {"_id": "00000000-0000-0000-0000-000000000101", "source_id": "00000000-0000-0000-0000-000000000001", "chunk_index": 0, "content": "Matching chunk 1", "embedding_vector": [0.1, 0.2, 0.3], "token_count": 3, "embedding_model": "text-embedding-3-small"},
        {"_id": "00000000-0000-0000-0000-000000000102", "source_id": "00000000-0000-0000-0000-000000000001", "chunk_index": 1, "content": "Irrelevant chunk 2", "embedding_vector": [0.9, 0.9, 0.9], "token_count": 3, "embedding_model": "models/gemini-embedding-001"},
        {"_id": "00000000-0000-0000-0000-000000000103", "source_id": "00000000-0000-0000-0000-000000000001", "chunk_index": 2, "content": "Missing embedding chunk", "token_count": 3, "embedding_model": "text-embedding-3-small"}, # should be skipped in test because embedding_vector is missing
    ]
    
    class AsyncIterator:
        def __init__(self, items):
            self.items = items
            self.idx = 0
        def __aiter__(self):
            return self
        async def __anext__(self):
            if self.idx < len(self.items):
                item = self.items[self.idx]
                self.idx += 1
                return item
            raise StopAsyncIteration
            
    mock_chunks_collection.find.return_value = AsyncIterator(mock_chunks)
    
    # Mock sources cursor
    mock_sources = [{"_id": "00000000-0000-0000-0000-000000000001", "source_name": "Test Document", "source_type": "pdf", "url": None, "bot_id": "00000000-0000-0000-0000-000000000002"}]
    mock_sources_collection = MagicMock()
    mock_sources_collection.find.return_value = AsyncIterator(mock_sources)
    
    mock_mongo_db = {
        "chunks": mock_chunks_collection,
        "knowledge_sources": mock_sources_collection
    }
    
    mock_mongo_client = MagicMock()
    mock_mongo_client.__getitem__.side_effect = lambda name: mock_mongo_db
    
    # Patch the mongo registry and settings
    from app.core.mongo import mongo_registry
    from app.core.config import settings
    
    orig_get_client = mongo_registry.get_client
    orig_mongo_url = settings.MONGODB_URL
    
    mongo_registry.get_client = MagicMock(return_value=mock_mongo_client)
    settings.MONGODB_URL = "mongodb://localhost:27017/chatbot"
    
    try:
        # Perform query
        results = await vector_search_service.search_similar_chunks(
            db=db_mock,
            bot_id="00000000-0000-0000-0000-000000000002",
            query_vector=[0.1, 0.2, 0.3],
            top_k=2,
            min_score=0.1
        )
        
        # Verify results - should only contain chunk 1 since chunk 2 uses a different embedding model
        assert len(results) == 1
        # First chunk should have high similarity with [0.1, 0.2, 0.3]
        assert results[0]["chunk"]["id"] == "00000000-0000-0000-0000-000000000101"
        assert results[0]["score"] > 0.99
        
    finally:
        # Restore
        mongo_registry.get_client = orig_get_client
        settings.MONGODB_URL = orig_mongo_url
        openai_embedding_service.get_active_model_name = orig_get_active_model_name
