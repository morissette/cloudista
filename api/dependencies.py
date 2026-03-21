import logging

import psycopg2
import psycopg2.extras
import psycopg2.pool
from config import settings
from fastapi import Depends, HTTPException

log = logging.getLogger(__name__)

_pg_pool: psycopg2.pool.ThreadedConnectionPool | None = None


def init_pool() -> None:
    global _pg_pool
    _pg_pool = psycopg2.pool.ThreadedConnectionPool(
        minconn=2,
        maxconn=10,
        host=settings.blog_db_host,
        port=settings.blog_db_port,
        user=settings.blog_db_user,
        password=settings.blog_db_password,
        dbname=settings.blog_db_name,
        cursor_factory=psycopg2.extras.RealDictCursor,
    )
    log.info("PostgreSQL connection pool initialised (min=2, max=10)")


def close_pool() -> None:
    if _pg_pool:
        _pg_pool.closeall()
        log.info("PostgreSQL connection pool closed")


def _get_pool() -> psycopg2.pool.ThreadedConnectionPool:
    if _pg_pool is None:
        raise HTTPException(status_code=503, detail="Database pool not initialised.")
    return _pg_pool


def get_pg_conn(pool: psycopg2.pool.ThreadedConnectionPool = Depends(_get_pool)):
    conn = pool.getconn()
    try:
        yield conn
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)
