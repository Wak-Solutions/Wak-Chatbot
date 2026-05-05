"""_db_companies.py — pool lifecycle + company resolution and credentials lookups."""

import logging
import time

import asyncpg

from config import DATABASE_URL

logger = logging.getLogger(__name__)

# In-process cache: phone_number_id → (company_id, monotonic_timestamp).
# TTL bounds staleness if a phone_number_id is ever reassigned.
_company_cache: dict[str, tuple[int, float]] = {}
_COMPANY_CACHE_TTL = 300.0  # seconds
_MAX_COMPANY_CACHE = 1_000


# ---------------------------------------------------------------------------
# Pool lifecycle
# ---------------------------------------------------------------------------


async def create_pool() -> None:
    """
    Opens a pool of 2–10 reusable connections to PostgreSQL.
    Called once on FastAPI startup in main.py.
    Strips query parameters from the URL because asyncpg doesn't support them.
    """
    import database
    clean_url = DATABASE_URL.split("?")[0]
    try:
        database.pool = await asyncpg.create_pool(
            dsn=clean_url,
            ssl="require",
            min_size=2,
            max_size=10,
            statement_cache_size=0,
        )
        logger.info("Connection pool created — min: 2, max: 10")
    except Exception as exc:
        logger.error("Failed to create connection pool: %s", exc, exc_info=True)
        raise


async def close_pool() -> None:
    """Cleanly closes all pool connections on FastAPI shutdown."""
    import database
    if database.pool:
        await database.pool.close()
        logger.info("Connection pool closed")


# ---------------------------------------------------------------------------
# Multi-tenancy: company resolution
# ---------------------------------------------------------------------------


async def get_company_by_phone_number_id(phone_number_id: str) -> int | None:
    """
    Looks up the company_id that owns this WhatsApp phone_number_id.
    Results are cached in-process so only the first message per process
    triggers a DB round-trip.

    Returns None if no active company owns this phone_number_id — the caller
    must discard the message and log the unroutable event. No fallback to
    company_id=1: silently routing unmatched messages to a default company
    causes cross-tenant data leakage.
    """
    import database
    cached = _company_cache.get(phone_number_id)
    if cached is not None:
        cached_id, cached_at = cached
        if (time.monotonic() - cached_at) < _COMPANY_CACHE_TTL:
            return cached_id

    try:
        async with database.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id FROM companies
                WHERE whatsapp_phone_number_id = $1
                LIMIT 1
                """,
                phone_number_id,
            )
        if not row:
            logger.error(
                "Unroutable webhook — no company owns phone_number_id=%s. "
                "Message will be discarded. Register this number in the company's WhatsApp settings.",
                phone_number_id,
            )
            # Do NOT cache None — the company may register this number shortly after.
            return None

        company_id = row["id"]
        logger.info(
            "Resolved company_id=%d for phone_number_id=%s",
            company_id,
            phone_number_id,
        )
        _company_cache[phone_number_id] = (company_id, time.monotonic())
        if len(_company_cache) > _MAX_COMPANY_CACHE:
            oldest = next(iter(_company_cache))
            del _company_cache[oldest]
        return company_id
    except Exception as exc:
        logger.error(
            "get_company_by_phone_number_id failed for phone_number_id=%s: %s",
            phone_number_id,
            exc,
            exc_info=True,
        )
        return None  # do not route to a fallback company on DB error
