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


# Mock MongoDB database and collections for tests
class MockCollection:
    def __init__(self):
        self.docs = []

    async def insert_one(self, doc):
        self.docs.append(doc)
        return MagicMock()

    def insert_many(self, docs):
        self.docs.extend(docs)
        return MagicMock()

    async def find_one(self, query):
        for doc in self.docs:
            match = True
            for k, v in query.items():
                if isinstance(v, dict) and "$in" in v:
                    if str(doc.get(k)) not in [str(x) for x in v["$in"]]:
                        match = False
                elif str(doc.get(k)) != str(v):
                    match = False
            if match:
                return doc
        return None

    def find(self, query):
        matched = []
        for doc in self.docs:
            match = True
            for k, v in query.items():
                if isinstance(v, dict) and "$in" in v:
                    if str(doc.get(k)) not in [str(x) for x in v["$in"]]:
                        match = False
                elif str(doc.get(k)) != str(v):
                    match = False
            if match:
                matched.append(doc)
        
        class AsyncCursor:
            def __init__(self, items):
                self.items = items
                self.index = 0
            
            def sort(self, *args, **kwargs):
                return self
                
            def limit(self, *args, **kwargs):
                return self
                
            def skip(self, *args, **kwargs):
                return self
                
            def __aiter__(self):
                return self
                
            async def __anext__(self):
                if self.index < len(self.items):
                    item = self.items[self.index]
                    self.index += 1
                    return item
                raise StopAsyncIteration
                
        return AsyncCursor(matched)

    @staticmethod
    def _matches_query(doc, query):
        """Check if a document matches a Mongo-style query dict."""
        for k, v in query.items():
            doc_val = doc.get(k)
            if isinstance(v, dict):
                if "$in" in v:
                    if str(doc_val) not in [str(x) for x in v["$in"]]:
                        return False
                if "$gte" in v:
                    if doc_val is None or doc_val < v["$gte"]:
                        return False
                if "$lte" in v:
                    if doc_val is None or doc_val > v["$lte"]:
                        return False
                if "$lt" in v:
                    if doc_val is None or doc_val >= v["$lt"]:
                        return False
                if "$gt" in v:
                    if doc_val is None or doc_val <= v["$gt"]:
                        return False
            else:
                if str(doc_val) != str(v):
                    return False
        return True

    async def count_documents(self, query):
        return sum(1 for doc in self.docs if self._matches_query(doc, query))

    async def update_one(self, query, update, upsert=False):
        doc = await self.find_one(query)
        if doc:
            if "$set" in update:
                for k, v in update["$set"].items():
                    doc[k] = v
        elif upsert:
            new_doc = {}
            if "$set" in update:
                for k, v in update["$set"].items():
                    new_doc[k] = v
            for k, v in query.items():
                if not isinstance(v, dict) and k not in new_doc:
                    new_doc[k] = v
            self.docs.append(new_doc)
        return MagicMock()

    async def delete_many(self, query):
        initial_len = len(self.docs)
        new_docs = []
        for doc in self.docs:
            match = True
            for k, v in query.items():
                if isinstance(v, dict) and "$in" in v:
                    if str(doc.get(k)) not in [str(x) for x in v["$in"]]:
                        match = False
                elif str(doc.get(k)) != str(v):
                    match = False
            if not match:
                new_docs.append(doc)
        self.docs = new_docs
        res = MagicMock()
        res.deleted_count = initial_len - len(self.docs)
        return res

    async def distinct(self, key, query=None):
        results = set()
        for doc in self.docs:
            if query:
                match = True
                for k, v in query.items():
                    if isinstance(v, dict) and "$in" in v:
                        if str(doc.get(k)) not in [str(x) for x in v["$in"]]:
                            match = False
                    elif str(doc.get(k)) != str(v):
                        match = False
                if not match:
                    continue
            if key in doc:
                results.add(doc[key])
        return list(results)

    def aggregate(self, pipeline):
        class AsyncCursor:
            def __aiter__(self):
                return self
            async def __anext__(self):
                raise StopAsyncIteration
        return AsyncCursor()


class MockDatabase:
    def __init__(self):
        self.collections = {
            "messages": MockCollection(),
            "chunks": MockCollection(),
            "conversations": MockCollection(),
            "documents": MockCollection(),
            "knowledge_sources": MockCollection(),
            "feedback_ratings": MockCollection(),
            "analytics_events": MockCollection(),
            "ingestion_jobs": MockCollection(),
            "url_crawls": MockCollection(),
            "export_jobs": MockCollection(),
            "widget_sessions": MockCollection(),
            # New collections
            "rate_limit_logs": MockCollection(),
            "typing_events": MockCollection(),
            "bot_analytics_snapshots": MockCollection(),
        }

    def __getitem__(self, name):
        if name not in self.collections:
            self.collections[name] = MockCollection()
        return self.collections[name]


_shared_mock_db = None


class MockMongoClient:
    def __init__(self, *args, **kwargs):
        global _shared_mock_db
        if _shared_mock_db is None:
            _shared_mock_db = MockDatabase()
        self.db = _shared_mock_db
        
    def __getitem__(self, name):
        return self.db

    def close(self):
        pass


from unittest.mock import MagicMock
@pytest.fixture(autouse=True)
def mock_mongo(monkeypatch):
    global _shared_mock_db
    _shared_mock_db = MockDatabase()
    monkeypatch.setattr("pymongo.MongoClient", MockMongoClient)
    import app.core.mongo
    monkeypatch.setattr(app.core.mongo, "AsyncIOMotorClient", MockMongoClient)
