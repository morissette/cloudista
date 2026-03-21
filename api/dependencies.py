import asyncio
import logging
from collections.abc import AsyncGenerator

import asyncpg
from config import settings
from fastapi import Depends, HTTPException, Request
from slowapi import Limiter

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Rate limiter — shared between main.py and blog_routes.py to avoid circular
# imports. Key on X-Real-IP (set by nginx, not spoofable by clients).
# ---------------------------------------------------------------------------
def _real_ip(request: Request) -> str:
    return (
        request.headers.get("X-Real-IP")
        or request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        or (request.client.host if request.client else "unknown")
    )


limiter = Limiter(key_func=_real_ip)

_pg_pool: asyncpg.Pool | None = None


async def init_pool() -> None:
    global _pg_pool
    _pg_pool = await asyncpg.create_pool(
        host=settings.blog_db_host,
        port=settings.blog_db_port,
        user=settings.blog_db_user,
        password=settings.blog_db_password,
        database=settings.blog_db_name,
        min_size=2,
        max_size=10,
        timeout=5.0,        # max seconds to wait for a connection
        command_timeout=30.0,
    )
    log.info("PostgreSQL connection pool initialised (min=2, max=10)")


async def close_pool() -> None:
    if _pg_pool:
        await _pg_pool.close()
        log.info("PostgreSQL connection pool closed")


def _get_pool() -> asyncpg.Pool:
    if _pg_pool is None:
        raise HTTPException(status_code=503, detail="Database pool not initialised.")
    return _pg_pool


async def get_pg_conn(
    pool: asyncpg.Pool = Depends(_get_pool),
) -> AsyncGenerator[asyncpg.Connection, None]:
    """Yield a pooled connection; 503 on exhaustion or timeout instead of hanging forever."""
    try:
        async with pool.acquire(timeout=5.0) as conn:
            yield conn
    except (asyncpg.TooManyConnectionsError, asyncio.TimeoutError):
        raise HTTPException(status_code=503, detail="Database temporarily unavailable.")
