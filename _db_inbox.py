"""_db_inbox.py — webhook idempotency + raw payload durability."""

import json
import logging

logger = logging.getLogger(__name__)


async def try_claim_message_id(message_id: str) -> bool:
    """
    Atomically claim a Meta message_id. Returns True if this is the first
    delivery (caller should enqueue), False if it was already claimed by an
    earlier retry of the same payload (caller should skip).

    Fail-open on DB error: prefer reprocessing (idempotent at the conversation
    layer is recoverable) over silent message loss.
    """
    import database
    try:
        async with database.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO processed_messages (message_id)
                VALUES ($1)
                ON CONFLICT (message_id) DO NOTHING
                RETURNING message_id
                """,
                message_id,
            )
        return row is not None
    except Exception as exc:
        logger.error(
            "try_claim_message_id failed — message_id=%s, error: %s",
            message_id, exc, exc_info=True,
        )
        return True


async def persist_raw_inbound(phone_number_id: str, payload: dict) -> None:
    """
    Persist a verified raw webhook payload so it can be replayed if the
    in-process background task dies before completing. Logged-and-swallowed
    on DB error — raising would force a Meta retry of a verified payload.
    """
    import database
    try:
        async with database.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO raw_inbound_messages (phone_number_id, payload)
                VALUES ($1, $2::jsonb)
                """,
                phone_number_id,
                json.dumps(payload),
            )
    except Exception as exc:
        logger.error(
            "persist_raw_inbound failed — phone_number_id=%s, error: %s",
            phone_number_id, exc, exc_info=True,
        )
