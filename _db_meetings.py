"""_db_meetings.py — meeting creation, lookup, and link-delivery scheduling queries."""

import logging
import uuid
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)


async def create_meeting_with_token(customer_phone: str, company_id: int = 1) -> str:
    """
    Creates a meeting record with a unique booking token (24 hr expiry).
    Returns the token UUID string.
    """
    import database
    token = str(uuid.uuid4())
    expires_at = datetime.now(timezone.utc) + timedelta(hours=24)
    try:
        async with database.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO meetings
                  (customer_phone, meeting_link, meeting_token, token_expires_at, status, company_id, created_at)
                VALUES ($1, '', $2, $3, 'pending', $4, NOW())
                """,
                customer_phone,
                token,
                expires_at,
                company_id,
            )
        logger.info("Meeting token created — token: %s", token[:8] + "...")
        return token
    except Exception as exc:
        logger.error("create_meeting_with_token failed: %s", exc, exc_info=True)
        raise


async def get_pending_meeting(customer_phone: str, company_id: int = 1) -> dict | None:
    """
    Returns the latest pending meeting for a customer within the given company, or None.
    """
    import database
    try:
        async with database.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, meeting_link, agreed_time, meeting_token, scheduled_at
                FROM meetings
                WHERE customer_phone = $1 AND status = 'pending' AND company_id = $2
                ORDER BY created_at DESC
                LIMIT 1
                """,
                customer_phone,
                company_id,
            )
        if row is None:
            return None
        return {
            "id": row["id"],
            "meeting_link": row["meeting_link"],
            "agreed_time": row["agreed_time"],
            "meeting_token": row["meeting_token"],
            "scheduled_at": row["scheduled_at"],
        }
    except Exception as exc:
        logger.error(
            "get_pending_meeting failed: %s", exc, exc_info=True
        )
        raise


async def update_meeting_time(meeting_id: int, agreed_time: str) -> None:
    """Saves the agreed date/time for a pending meeting."""
    import database
    try:
        async with database.pool.acquire() as conn:
            await conn.execute(
                "UPDATE meetings SET agreed_time = $1 WHERE id = $2",
                agreed_time,
                meeting_id,
            )
        logger.info(
            "Meeting time updated — meeting_id: %d, agreed_time: %s",
            meeting_id,
            agreed_time,
        )
    except Exception as exc:
        logger.error(
            "update_meeting_time failed — meeting_id: %d, error: %s",
            meeting_id,
            exc,
            exc_info=True,
        )
        raise


async def get_meetings_to_notify() -> list[dict]:
    """
    Returns meetings within 15 minutes of start time that haven't had
    their link sent yet.
    """
    import database
    try:
        async with database.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, customer_phone, meeting_link, meeting_token, company_id
                FROM meetings
                WHERE status != 'completed'
                  AND link_sent = FALSE
                  AND meeting_link != ''
                  AND scheduled_at IS NOT NULL
                  AND scheduled_at <= NOW() + INTERVAL '15 minutes'
                  AND scheduled_at >= NOW() - INTERVAL '30 minutes'
                """
            )
        result = [dict(r) for r in rows]
        if result:
            logger.info(
                "Meetings to notify — count: %d", len(result)
            )
        return result
    except Exception as exc:
        logger.error(
            "get_meetings_to_notify failed: %s", exc, exc_info=True
        )
        raise


async def mark_link_sent(meeting_id: int) -> None:
    """Marks the meeting link as sent to prevent duplicate delivery."""
    import database
    try:
        async with database.pool.acquire() as conn:
            await conn.execute(
                "UPDATE meetings SET link_sent = TRUE WHERE id = $1",
                meeting_id,
            )
    except Exception as exc:
        logger.error(
            "mark_link_sent failed — meeting_id: %d, error: %s",
            meeting_id,
            exc,
            exc_info=True,
        )
        raise
