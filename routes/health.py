"""health.py — public /health probe used by Railway and external monitors (no auth)."""

import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse

import database

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/health")
async def health_check():
    """
    Returns 200 if the app and database are healthy, 503 if the database
    is unreachable. Never raises — all errors are caught and reported.
    """
    try:
        async with database.pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        return JSONResponse(
            content={"status": "ok", "database": "connected"},
            status_code=200,
        )
    except Exception as exc:
        logger.error("Health check — database unreachable: %s", exc)
        return JSONResponse(
            content={"status": "degraded", "database": "unreachable"},
            status_code=503,
        )
