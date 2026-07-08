import pytest
import uuid
from httpx import AsyncClient
from unittest.mock import patch, AsyncMock
from app.core.security import hash_password
from app.models.user import User

@pytest.mark.asyncio
async def test_end_to_end_acceptance_flow(client: AsyncClient, db_session):
    # 1. Seed superadmin user & regular user
    superadmin = User(
        id=uuid.uuid4(),
        email="admin@example.com",
        password_hash=hash_password("adminpass"),
        role="superadmin"
    )
    regular_user = User(
        id=uuid.uuid4(),
        email="user@example.com",
        password_hash=hash_password("userpass"),
        role="user"
    )
    db_session.add(superadmin)
    db_session.add(regular_user)
    await db_session.commit()

    # 2. Login as superadmin
    login_payload = {"email": "admin@example.com", "password": "adminpass"}
    login_res = await client.post("/api/v1/auth/login", json=login_payload)
    assert login_res.status_code == 200
    token_data = login_res.json()["data"]
    admin_token = token_data["access_token"]
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    # 3. Login as regular user
    login_payload_user = {"email": "user@example.com", "password": "userpass"}
    login_res_user = await client.post("/api/v1/auth/login", json=login_payload_user)
    assert login_res_user.status_code == 200
    token_data_user = login_res_user.json()["data"]
    user_token = token_data_user["access_token"]
    user_headers = {"Authorization": f"Bearer {user_token}"}

    # 4. Create a Bot as superadmin
    bot_payload = {
        "name": "Acceptance Bot",
        "is_active": True
    }
    bot_res = await client.post("/api/v1/bots", json=bot_payload, headers=admin_headers)
    assert bot_res.status_code == 201
    bot_data = bot_res.json()["data"]
    bot_id = bot_data["id"]

    # 5. Access bot details as creator (superadmin)
    get_bot_res = await client.get(f"/api/v1/bots/{bot_id}", headers=admin_headers)
    assert get_bot_res.status_code == 200

    # 6. Access bot details as regular user (unauthorized) -> should fail with 404
    get_bot_user_res = await client.get(f"/api/v1/bots/{bot_id}", headers=user_headers)
    assert get_bot_user_res.status_code == 404

    # 7. Start a public widget conversation
    conv_payload = {"bot_id": bot_id}
    conv_res = await client.post("/api/v1/public/conversations", json=conv_payload)
    assert conv_res.status_code == 201
    conv_data = conv_res.json()["data"]
    conversation_id = conv_data["conversation_id"]
    assert "welcome_message" in conv_data

    # 8. Send a public guest message (mocking the AI pipeline)
    mock_pipeline = AsyncMock(return_value={"answer": "Mocked response", "citations": []})
    with patch("app.api.v1.endpoints.public.ai_response_pipeline_service.generate_response", mock_pipeline):
        msg_payload = {"content": "Hello, bot! How do I build a SaaS application?"}
        msg_res = await client.post(
            f"/api/v1/public/conversations/{conversation_id}/messages",
            json=msg_payload
        )
        assert msg_res.status_code == 201
        msg_data = msg_res.json()["data"]
        assert msg_data["content"] == "Mocked response"
