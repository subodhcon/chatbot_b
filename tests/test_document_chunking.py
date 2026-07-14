import pytest
from app.services.document_chunking import document_chunking_service

def test_chunk_text_basic():
    """
    Test basic document chunking with a simple text.
    """
    text = "This is sentence one. This is sentence two. This is sentence three."
    # Use small chunk size (e.g. 5 tokens) to force splits
    chunks = document_chunking_service.chunk_text(text, chunk_size=5, overlap=1)
    
    assert len(chunks) > 0
    for chunk in chunks:
        assert "content" in chunk
        assert "token_count" in chunk
        assert chunk["token_count"] <= 5

def test_chunk_text_scaling():
    """
    Test that default character-scale parameters (e.g. 3000) are automatically scaled.
    """
    text = "Word " * 2000
    chunks = document_chunking_service.chunk_text(text, chunk_size=3000, overlap=600)
    
    # 3000 characters would scale to 750 tokens
    # 2000 words is around 2000 tokens, so it should split into multiple chunks
    assert len(chunks) > 1
    for chunk in chunks:
        assert chunk["token_count"] <= 750
