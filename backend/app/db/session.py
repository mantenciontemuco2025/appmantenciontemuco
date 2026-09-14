from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.core.config import settings

_engine_kwargs = {
    "echo": False,
    # Detect a dead/stale connection before handing it to a request.
    "pool_pre_ping": True,
}

# SQLite (used by the test suite) does not accept PostgreSQL pool arguments.
# Production uses PostgreSQL/asyncpg, where bounded pooling prevents an
# unbounded number of connections when many users arrive at once.
if settings.DATABASE_URL.startswith("postgresql"):
    _engine_kwargs.update(
        pool_size=settings.DB_POOL_SIZE,
        max_overflow=settings.DB_MAX_OVERFLOW,
        pool_timeout=settings.DB_POOL_TIMEOUT,
        pool_recycle=settings.DB_POOL_RECYCLE,
    )

engine = create_async_engine(settings.DATABASE_URL, **_engine_kwargs)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db() -> AsyncSession:
    async with async_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
