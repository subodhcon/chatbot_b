from typing import AsyncGenerator, Generator
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, Session
from app.core.config import settings

is_sqlite = settings.DATABASE_URL.startswith("sqlite")

# Sync engine config
connect_args = {"check_same_thread": False} if is_sqlite else {}
engine_kwargs = {}
if not is_sqlite:
    engine_kwargs.update({
        "pool_size": 10,
        "max_overflow": 20,
    })

engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    connect_args=connect_args,
    **engine_kwargs
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Async engine config
async_engine_kwargs = {}
if not is_sqlite:
    async_engine_kwargs.update({
        "pool_size": 10,
        "max_overflow": 20,
    })

async_engine = create_async_engine(
    settings.async_database_url,
    pool_pre_ping=True,
    **async_engine_kwargs
)
AsyncSessionLocal = sessionmaker(
    autocommit=False, 
    autoflush=False, 
    bind=async_engine, 
    class_=AsyncSession,
    expire_on_commit=False,
)

# Dependencies to yield database sessions
def get_db() -> Generator[Session, None, None]:
    """
    Sync DB session provider.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

async def get_async_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Async DB session provider.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
