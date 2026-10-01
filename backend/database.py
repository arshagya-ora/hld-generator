"""
Database Configuration
SQLAlchemy async engine and session management
"""
from sqlalchemy import event
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import NullPool
from typing import AsyncGenerator
import uuid

from config import settings

# Create async engine — adapt settings for SQLite vs PostgreSQL
_is_sqlite = settings.DATABASE_URL.startswith("sqlite")

if _is_sqlite:
    engine = create_async_engine(
        settings.DATABASE_URL,
        echo=settings.DEBUG,
        connect_args={
            "check_same_thread": False,
            "timeout": 30,
        },
        poolclass=NullPool,
    )
else:
    engine = create_async_engine(
        settings.DATABASE_URL,
        echo=settings.DEBUG,
        pool_size=settings.DATABASE_POOL_SIZE,
        max_overflow=settings.DATABASE_MAX_OVERFLOW,
        pool_timeout=settings.DATABASE_POOL_TIMEOUT,
        pool_recycle=settings.DATABASE_POOL_RECYCLE,
        pool_pre_ping=True,
        connect_args={
            "server_settings": {
                "application_name": "hld_generator_backend",
                "jit": "off",
            },
            "timeout": 10,
            "command_timeout": 30,
        },
    )

if _is_sqlite:
    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

# Create async session factory
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

# Import the canonical Base from models so there is only ONE metadata registry.
# database.py previously defined its own Base = declarative_base() which was
# DIFFERENT from models/base.py's Base, causing init_db() to create zero tables.
from models.base import Base


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Dependency for getting async database sessions
    Usage:
        @app.get("/endpoint")
        async def endpoint(db: AsyncSession = Depends(get_db)):
            ...
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def set_tenant_context(session: AsyncSession, tenant_id: uuid.UUID):
    """
    Set PostgreSQL session variable for Row-Level Security
    This enables tenant isolation at the database level
    """
    from sqlalchemy import text
    await session.execute(
        text("SET app.current_tenant = :tenant_id"),
        {"tenant_id": str(tenant_id)}
    )


async def init_db():
    """Initialize database - create all tables"""
    # Import all models so they register with Base.metadata
    import models  # noqa: F401 — triggers all model registrations
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def drop_db():
    """Drop all database tables - USE WITH CAUTION"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
