import pytest
import uuid
from app.models.user import User
from app.models.bot import Bot
from app.models.bot_manager import BotManager
from app.dependencies import has_bot_access

@pytest.mark.asyncio
async def test_has_bot_access_superadmin(db_session):
    superadmin = User(
        id=uuid.uuid4(),
        email="super@example.com",
        password_hash="...",
        role="superadmin"
    )
    # Even if bot doesn't exist, superadmin should have access or return True
    bot_id = uuid.uuid4()
    access = await has_bot_access(db_session, superadmin, bot_id)
    assert access is True

@pytest.mark.asyncio
async def test_has_bot_access_creator(db_session):
    user = User(
        id=uuid.uuid4(),
        email="creator@example.com",
        password_hash="...",
        role="user"
    )
    db_session.add(user)
    
    bot = Bot(
        id=uuid.uuid4(),
        name="Test Bot",
        slug="test-bot",
        created_by=user.id
    )
    db_session.add(bot)
    await db_session.commit()
    
    access = await has_bot_access(db_session, user, bot.id)
    assert access is True

@pytest.mark.asyncio
async def test_has_bot_access_manager(db_session):
    creator = User(
        id=uuid.uuid4(),
        email="creator2@example.com",
        password_hash="...",
        role="user"
    )
    manager = User(
        id=uuid.uuid4(),
        email="manager@example.com",
        password_hash="...",
        role="user"
    )
    db_session.add(creator)
    db_session.add(manager)
    
    bot = Bot(
        id=uuid.uuid4(),
        name="Managed Bot",
        slug="managed-bot",
        created_by=creator.id
    )
    db_session.add(bot)
    await db_session.commit()
    
    bot_manager = BotManager(
        id=uuid.uuid4(),
        bot_id=bot.id,
        user_id=manager.id,
        role="editor"
    )
    db_session.add(bot_manager)
    await db_session.commit()
    
    access = await has_bot_access(db_session, manager, bot.id)
    assert access is True

@pytest.mark.asyncio
async def test_has_bot_access_unauthorized(db_session):
    creator = User(
        id=uuid.uuid4(),
        email="creator3@example.com",
        password_hash="...",
        role="user"
    )
    unauthorized = User(
        id=uuid.uuid4(),
        email="unauthorized@example.com",
        password_hash="...",
        role="user"
    )
    db_session.add(creator)
    db_session.add(unauthorized)
    
    bot = Bot(
        id=uuid.uuid4(),
        name="Private Bot",
        slug="private-bot",
        created_by=creator.id
    )
    db_session.add(bot)
    await db_session.commit()
    
    access = await has_bot_access(db_session, unauthorized, bot.id)
    assert access is False
