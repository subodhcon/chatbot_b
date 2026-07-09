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

    # 9. Try to delete the active regular user -> should fail with 400
    delete_res_active = await client.delete(f"/api/v1/users/{regular_user.id}", headers=admin_headers)
    assert delete_res_active.status_code == 400
    assert delete_res_active.json()["error"]["code"] == "ACTIVE_USER_DELETION_PREVENTED"

    # Deactivate the user first
    status_res = await client.patch(f"/api/v1/users/{regular_user.id}/status", headers=admin_headers)
    assert status_res.status_code == 200

    # Assign a bot to this user to test safety check 3 (assigned bots exist)
    assign_res = await client.post(f"/api/v1/users/{regular_user.id}/bots/{bot_id}", headers=admin_headers)
    assert assign_res.status_code == 200

    # Try to delete the deactivated user who is assigned to a bot -> should fail with 400
    delete_res_assigned = await client.delete(f"/api/v1/users/{regular_user.id}", headers=admin_headers)
    assert delete_res_assigned.status_code == 400
    assert delete_res_assigned.json()["error"]["code"] == "ASSIGNED_BOTS_EXIST"

    # Unassign the bot
    unassign_res = await client.delete(f"/api/v1/users/{regular_user.id}/bots/{bot_id}", headers=admin_headers)
    assert unassign_res.status_code == 200

    # Now delete the deactivated and unassigned user -> should succeed with 200
    delete_res = await client.delete(f"/api/v1/users/{regular_user.id}", headers=admin_headers)
    assert delete_res.status_code == 200
    assert delete_res.json()["data"]["deleted"] is True

    # 10. Verify regular user is no longer fetchable/present in DB
    get_users_res = await client.get("/api/v1/users", headers=admin_headers)
    assert get_users_res.status_code == 200
    user_ids = [u["id"] for u in get_users_res.json()["data"]]
    assert str(regular_user.id) not in user_ids

    # 11. Test Profile Update endpoint (PUT /api/v1/auth/profile)
    # A. Superadmin attempts to change their email -> should fail with 400
    profile_payload_fail = {"name": "Super Admin Updated", "email": "admin_updated@example.com"}
    profile_res_fail = await client.put("/api/v1/auth/profile", json=profile_payload_fail, headers=admin_headers)
    assert profile_res_fail.status_code == 400
    assert profile_res_fail.json()["error"]["code"] == "SUPERADMIN_EMAIL_CHANGE_PREVENTED"

    # B. Superadmin updates their name but keeps current email -> should succeed with 200
    profile_payload_success = {"name": "Super Admin Updated", "email": "admin@example.com"}
    profile_res_success = await client.put("/api/v1/auth/profile", json=profile_payload_success, headers=admin_headers)
    assert profile_res_success.status_code == 200
    assert profile_res_success.json()["data"]["name"] == "Super Admin Updated"
    assert profile_res_success.json()["data"]["email"] == "admin@example.com"

    # 12. Test Password Update endpoint (PUT /api/v1/auth/password)
    password_payload = {"current_password": "adminpass", "new_password": "newadminpass"}
    password_res = await client.put("/api/v1/auth/password", json=password_payload, headers=admin_headers)
    assert password_res.status_code == 200
    assert password_res.json()["data"]["message"] == "Password updated successfully."

    # Verify we can login with the updated profile name and new password
    login_payload_new = {"email": "admin@example.com", "password": "newadminpass"}
    login_res_new = await client.post("/api/v1/auth/login", json=login_payload_new)
    assert login_res_new.status_code == 200

