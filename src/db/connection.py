# src/db/connection.py
"""
Engine async y session factory para SQLAlchemy + asyncpg.
Se reutiliza en toda la aplicación; no se instancia más de una vez.
"""
from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.config import settings

# ── Engine async singleton ────────────────────────────────────────────────────
engine_kwargs = {"echo": False, "pool_pre_ping": True}
if not settings.database_url.startswith("sqlite"):
    engine_kwargs.update({"pool_size": 10, "max_overflow": 20})

engine = create_async_engine(
    settings.database_url,
    **engine_kwargs,
)

# ── Session factory ───────────────────────────────────────────────────────────
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,  # Evita lazy-load después del commit en modo async
    autoflush=False,
    autocommit=False,
)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Dependencia FastAPI: genera una sesión async y la cierra al terminar.

    Uso:
        @app.get("/")
        async def endpoint(db: AsyncSession = Depends(get_session)):
            ...
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise