import asyncio
import pytest
import pytest_asyncio
from typing import AsyncGenerator, Generator
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from httpx import AsyncClient, ASGITransport

from app.core.config import settings
from app.db.base_class import Base
from app.db.session import get_async_db
from app.utils.redis import get_redis
from app.main import app

# Use a test SQLite database path
TEST_DATABASE_URL = "sqlite+aiosqlite:///./test_chatbot.db"

# Custom compiler rule to render JSONB as JSON in SQLite
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB

@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(type_, compiler, **kw):
    return "JSON"


@pytest.fixture(scope="session")
def event_loop() -> Generator:
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()

# Mock Redis class for testing
class MockRedis:
    def __init__(self):
        self.is_mock = True
        self.data = {}

    async def ping(self):
        return True

    async def get(self, key):
        return self.data.get(key)

    async def set(self, key, value, ex=None):
        self.data[key] = value
        return True

    async def delete(self, key):
        if key in self.data:
            del self.data[key]
        return True

    async def close(self):
        pass

@pytest_asyncio.fixture(scope="session")
async def db_engine():
    # Force test database URL
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
        
    yield engine
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        
    await engine.dispose()

@pytest_asyncio.fixture
async def db_session(db_engine) -> AsyncGenerator[AsyncSession, None]:
    connection = await db_engine.connect()
    transaction = await connection.begin()
    
    TestingSessionLocal = sessionmaker(
        bind=connection,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False
    )
    
    session = TestingSessionLocal()
    
    yield session
    
    await session.close()
    await transaction.rollback()
    await connection.close()

@pytest_asyncio.fixture
async def client(db_session) -> AsyncGenerator[AsyncClient, None]:
    # Override dependencies
    async def override_get_async_db():
        yield db_session

    async def override_get_redis():
        yield MockRedis()

    app.dependency_overrides[get_async_db] = override_get_async_db
    app.dependency_overrides[get_redis] = override_get_redis

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver"
    ) as ac:
        yield ac

    app.dependency_overrides.clear()
