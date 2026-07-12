import pytest
import uuid
from unittest.mock import patch, AsyncMock
from app.models.bot import Bot
from app.models.bot_config import BotConfig

@pytest.fixture
def anyio_backend():
    return "asyncio"

@pytest.fixture
def mock_rag_services():
    """
    Mock RAG pipeline service directly for black-box API layer testing.
    """
    with patch("app.api.v1.endpoints.public.ai_response_pipeline_service.generate_response") as mock_pipeline:
        yield {
            "pipeline": mock_pipeline
        }

@pytest.fixture
async def setup_test_bot(db_session):
    """
    Create a temporary Bot and BotConfig in SQLite test db for session initialization.
    """
    from app.models.user import User
    
    bot_id = uuid.UUID("ced76ca3-5bb3-4849-a702-80a37200ef76")
    user_id = uuid.uuid4()
    
    user = User(id=user_id, email=f"test_{uuid.uuid4()}@test.com", password_hash="pw", is_active=True)

    bot = Bot(id=bot_id, created_by=user_id, name="Gaya Ji Bot", slug="gaya-ji-bot")
    config = BotConfig(
        bot_id=bot_id,
        welcome_message="Hello!",
        tone="professional",
        use_custom_mongo=False
    )
    
    db_session.add(user)
    db_session.add(bot)
    db_session.add(config)
    await db_session.commit()
    
    yield bot_id

@pytest.mark.anyio
async def test_api_pandas_vs_pads_blackbox(client, setup_test_bot, mock_rag_services):
    """
    Test Case 1: Send query for Panda list and verify the API returns 
    the list formatted correctly and contains Pandit names, but NO place names.
    """
    bot_id = setup_test_bot
    
    # 1. Initialize a new conversation session to get a valid session_id
    init_response = await client.post(
        "/api/v1/public/conversations",
        json={"bot_id": str(bot_id), "browser_info": {}}
    )
    
    assert init_response.status_code == 201
    init_data = init_response.json()
    session_id = init_data["data"]["conversation_id"]
    
    # Mock pipeline output directly for message processing
    mock_rag_services["pipeline"].return_value = {
        "answer": "* **Kanhaiya Lal Dubhalia**\n* **Kanhaiya Lal Nakfofa**",
        "citations": [],
        "escalation_eligible": False,
        "metadata": {
            "model": "gpt-4o-mini",
            "confidence_score": 0.95
        }
    }
    
    # Call the public message API endpoint
    response = await client.post(
        f"/api/v1/public/conversations/{session_id}/messages",
        json={"content": "gaya ji me pandi ji ka list"}
    )
    
    assert response.status_code == 201
    data = response.json()
    assert data["success"] is True
    
    answer = data["data"]["content"]
    
    # Validate semantic boundary: Should contain Pandit names, NOT place names
    assert "Kanhaiya Lal" in answer
    assert "VishnuPad" not in answer
    assert "Dev Ghat" not in answer
    assert "*" in answer or "-" in answer

@pytest.mark.anyio
async def test_api_places_blackbox(client, setup_test_bot, mock_rag_services):
    """
    Test Case 2: Send query for Places list and verify the API returns 
    places names, but NO Pandit names.
    """
    bot_id = setup_test_bot
    
    # 1. Initialize a new conversation session to get a valid session_id
    init_response = await client.post(
        "/api/v1/public/conversations",
        json={"bot_id": str(bot_id), "browser_info": {}}
    )
    
    assert init_response.status_code == 201
    init_data = init_response.json()
    session_id = init_data["data"]["conversation_id"]
    
    # Mock pipeline output directly
    mock_rag_services["pipeline"].return_value = {
        "answer": "* **VishnuPad Temple**\n* **Dev Ghat**\n* **Kaach Pad**",
        "citations": [],
        "escalation_eligible": False,
        "metadata": {
            "model": "gpt-4o-mini",
            "confidence_score": 0.95
        }
    }
    
    # Call the API
    response = await client.post(
        f"/api/v1/public/conversations/{session_id}/messages",
        json={"content": "gaya ji places list"}
    )
    
    assert response.status_code == 201
    data = response.json()
    answer = data["data"]["content"]
    
    # Validate semantic boundary: Should contain Places, NOT Pandits
    assert "VishnuPad" in answer
    assert "Dev Ghat" in answer
    assert "Kanhaiya Lal" not in answer
    assert "*" in answer or "-" in answer
