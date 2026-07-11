import pytest
import uuid
from httpx import AsyncClient
from unittest.mock import patch, AsyncMock
from app.core.security import hash_password
from app.models.user import User
from sqlalchemy import select

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

    # 10b. Test that Admin/Superadmin cannot change a user's email via the PUT /api/v1/users/{user_id} endpoint
    # Let's temporarily seed a target user to test administrative update constraints
    temp_user_id = uuid.uuid4()
    from app.models.user import User as DbUser
    temp_user = DbUser(
        id=temp_user_id,
        email="temp_user@example.com",
        password_hash=hash_password("temppass"),
        role="user"
    )
    db_session.add(temp_user)
    await db_session.commit()

    admin_update_payload_fail = {
        "email": "temp_user_changed@example.com",
        "name": "Temp User Edit"
    }
    admin_update_res_fail = await client.put(
        f"/api/v1/users/{temp_user_id}",
        json=admin_update_payload_fail,
        headers=admin_headers
    )
    assert admin_update_res_fail.status_code == 400
    assert admin_update_res_fail.json()["error"]["code"] == "EMAIL_CHANGE_PREVENTED"

    # Clean up temp user
    await db_session.delete(temp_user)
    await db_session.commit()

    # 11. Test Profile Update endpoint (PUT /api/v1/auth/profile)
    # A. Superadmin attempts to change their email -> should fail with 400
    profile_payload_fail = {"name": "Super Admin Updated", "email": "admin_updated@example.com"}
    profile_res_fail = await client.put("/api/v1/auth/profile", json=profile_payload_fail, headers=admin_headers)
    assert profile_res_fail.status_code == 400
    assert profile_res_fail.json()["error"]["code"] == "EMAIL_CHANGE_PREVENTED"

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

    # 13. Test Bot Config update with custom MongoDB Atlas settings via API
    mongo_payload = {
        "use_custom_mongo": True,
        "mongo_uri": "mongodb://localhost:27017",
        "mongo_db_name": "bot_abc_db"
    }
    config_update_res = await client.patch(
        f"/api/v1/bots/{bot_id}/config",
        json=mongo_payload,
        headers=admin_headers
    )
    assert config_update_res.status_code == 200
    config_data = config_update_res.json()["data"]["config"]
    assert config_data["use_custom_mongo"] is True
    assert config_data["mongo_db_name"] == "bot_abc_db"

    # 14. Verify URI is returned as encrypted (non-plaintext) in API response
    assert config_data.get("mongo_uri") != "mongodb://localhost:27017"

    # 15. Test Mongo connection registry caching
    from app.core.mongo import mongo_registry
    from app.core.security import encrypt_string

    encrypted_uri = encrypt_string("mongodb://localhost:27017")
    mongo_client_1 = mongo_registry.get_client(bot_id, encrypted_uri)
    assert mongo_client_1 is not None
    mongo_client_2 = mongo_registry.get_client(bot_id, encrypted_uri)
    assert mongo_client_2 is mongo_client_1  # same cached instance

    # 16. Test message service MongoDB routing by mocking _get_mongo_collection.
    # We use a lightweight in-process fake collection so no real MongoDB server
    # or external test package is needed.
    import datetime as _dt

    class _FakeCursor:
        def __init__(self, docs):
            self._docs = docs
        def sort(self, *a, **kw): return self
        def skip(self, n): self._docs = self._docs[n:]; return self
        def limit(self, n): self._docs = self._docs[:n] if n else self._docs; return self
        def __aiter__(self): self._i = iter(self._docs); return self
        async def __anext__(self):
            try: return next(self._i)
            except StopIteration: raise StopAsyncIteration
        async def to_list(self, length=None):
            return self._docs[:length] if length else self._docs

    class _FakeCollection:
        def __init__(self): self._store = []
        async def insert_one(self, doc): self._store.append(dict(doc))
        def find(self, filt=None):
            if filt:
                results = [d for d in self._store if all(d.get(k) == v for k, v in filt.items())]
            else:
                results = list(self._store)
            return _FakeCursor(results)

    fake_col = _FakeCollection()
    mock_bot_id = uuid.UUID(bot_id)

    from app.services.message import message_service, MessageService

    async def mock_get_mongo_collection(self_inner, db, conv_id):
        return fake_col, mock_bot_id

    with patch.object(MessageService, "_get_mongo_collection", mock_get_mongo_collection):
        # Save user message — routed to fake in-memory MongoDB collection
        user_msg = await message_service.save_user_message(
            db_session,
            conversation_id=uuid.UUID(conversation_id),
            content="I have a question about custom MongoDB.",
        )
        assert user_msg is not None
        assert user_msg.content == "I have a question about custom MongoDB."

        # Save assistant message
        bot_msg = await message_service.save_assistant_message(
            db_session,
            conversation_id=uuid.UUID(conversation_id),
            content="This response is saved in your MongoDB cluster!",
        )
        assert bot_msg is not None
        assert bot_msg.content == "This response is saved in your MongoDB cluster!"

        # Fetch history — should return only the 2 messages from mock MongoDB
        history = await message_service.fetch_conversation_history(
            db_session,
            conversation_id=uuid.UUID(conversation_id),
        )
        assert len(history) == 2
        assert history[0].content == "I have a question about custom MongoDB."
        assert history[1].content == "This response is saved in your MongoDB cluster!"

        # Verify directly from the fake collection
        mongo_docs = await fake_col.find(
            {"conversation_id": conversation_id}
        ).to_list(length=10)
        assert len(mongo_docs) == 2
        assert mongo_docs[0]["content"] == "I have a question about custom MongoDB."
        assert mongo_docs[0]["sender"] == "user"

    mongo_registry.close_client(bot_id)

