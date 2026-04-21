"""
memory.py — conversation history load and save.
"""

import logging
import uuid

import database
from config import MEMORY_WINDOW

logger = logging.getLogger(__name__)


def _mask_phone(phone: str) -> str:
    if not phone or len(phone) < 4:
        return "****"
    return f"****{phone[-4:]}"


async def load_history(customer_phone: str, company_id: int = 1) -> list[dict]:
    """
    Loads the last MEMORY_WINDOW messages for a customer from the messages table
    and returns them formatted as OpenAI conversation history.

    Returns an empty list for new customers — agent.py will then follow
    STEP 0 and send the mandatory opening message.
    """
    try:
        async with database.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT role, message_text
                FROM (
                    SELECT sender     AS role,
                           message_text,
                           created_at
                    FROM   messages
                    WHERE  customer_phone = $1 AND company_id = $3
                    ORDER  BY created_at DESC
                    LIMIT  $2
                ) recent_messages
                ORDER BY created_at ASC
                """,
                customer_phone,
                MEMORY_WINDOW,
                company_id,
            )

        if not rows:
            logger.info(
                "[INFO] [memory] No history found (new customer) — phone: %s",
                _mask_phone(customer_phone),
            )
            return []

        history = [
            {
                "role": "user" if row["role"] == "customer" else "assistant",
                "content": row["message_text"],
            }
            for row in rows
        ]
        logger.info(
            "[INFO] [memory] History loaded — phone: %s, messages: %d",
            _mask_phone(customer_phone),
            len(history),
        )
        return history

    except Exception as exc:
        logger.error(
            "[ERROR] [memory] load_history failed — phone: %s, error: %s",
            _mask_phone(customer_phone),
            exc,
            exc_info=True,
        )
        raise


async def get_conversation_id(customer_phone: str, company_id: int) -> str | None:
    """
    Return the active conversation_id for this customer within the last 24 hours,
    or None if no session exists yet.
    """
    try:
        async with database.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT conversation_id FROM messages
                WHERE customer_phone = $1 AND company_id = $2
                  AND conversation_id IS NOT NULL
                  AND created_at > NOW() - INTERVAL '24 hours'
                ORDER BY created_at DESC LIMIT 1
                """,
                customer_phone,
                company_id,
            )
        return str(row["conversation_id"]) if row else None
    except Exception as exc:
        logger.error(
            "[ERROR] [memory] get_conversation_id failed — phone: %s, error: %s",
            _mask_phone(customer_phone),
            exc,
        )
        return None


async def save_message(
    customer_phone: str,
    direction: str,
    message_text: str,
    sender: str = None,
    media_type: str = None,
    media_url: str = None,
    transcription: str = None,
    company_id: int = 1,
) -> None:
    """
    Saves a single message to the messages table.

    Args:
        customer_phone: The customer's WhatsApp number.
        direction:      "inbound" or "outbound".
        message_text:   Text content (transcription for voice notes).
        sender:         Optional override — defaults to "customer"/"ai".
        media_type:     "audio" for voice notes, None for text.
        media_url:      URL to stored audio (None for text).
        transcription:  Whisper output (None for text messages).
        company_id:     The company this message belongs to.
    """
    if sender is None:
        sender = "customer" if direction == "inbound" else "ai"

    try:
        async with database.pool.acquire() as conn:
            # Resolve conversation_id: reuse if within 24 hours, else start a new session
            row = await conn.fetchrow(
                """
                SELECT conversation_id FROM messages
                WHERE customer_phone = $1 AND company_id = $2
                  AND conversation_id IS NOT NULL
                  AND created_at > NOW() - INTERVAL '24 hours'
                ORDER BY created_at DESC LIMIT 1
                """,
                customer_phone,
                company_id,
            )
            conversation_id = str(row["conversation_id"]) if row else str(uuid.uuid4())

            await conn.execute(
                """
                INSERT INTO messages
                  (customer_phone, direction, sender, message_text,
                   media_type, media_url, transcription, company_id, created_at,
                   conversation_id)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, NOW(), $9::uuid)
                """,
                customer_phone,
                direction,
                sender,
                message_text,
                media_type,
                media_url,
                transcription,
                company_id,
                conversation_id,
            )
        logger.info(
            "[INFO] [memory] Message saved — phone: %s, direction: %s, sender: %s, media_type: %s",
            _mask_phone(customer_phone),
            direction,
            sender,
            media_type or "text",
        )
    except Exception as exc:
        logger.error(
            "[ERROR] [memory] save_message failed — phone: %s, direction: %s, error: %s",
            _mask_phone(customer_phone),
            direction,
            exc,
            exc_info=True,
        )
        raise

    # Auto-add customer to contacts on first inbound message.
    if direction == "inbound":
        await database.auto_capture_contact(customer_phone, company_id)
