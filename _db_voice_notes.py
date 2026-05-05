"""_db_voice_notes.py — voice note storage and retrieval queries."""

import logging

logger = logging.getLogger(__name__)


async def store_voice_note(audio_bytes: bytes, mime_type: str, company_id: int) -> str:
    """
    Persist voice note audio in the voice_notes table.
    Returns the UUID string that identifies this recording.
    """
    import database
    try:
        async with database.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO voice_notes (audio_data, mime_type, company_id)
                VALUES ($1, $2, $3)
                RETURNING id::text
                """,
                audio_bytes,
                mime_type,
                company_id,
            )
        audio_id = row["id"]
        logger.info(
            "Voice note stored — id: %s, size_bytes: %d, mime: %s",
            audio_id[:8] + "...",
            len(audio_bytes),
            mime_type,
        )
        return audio_id
    except Exception as exc:
        logger.error(
            "store_voice_note failed — mime: %s, error: %s",
            mime_type,
            exc,
            exc_info=True,
        )
        raise


async def get_voice_note(audio_id: str, company_id: int) -> dict | None:
    """
    Fetch a voice note by its UUID.
    Returns dict with 'audio_data' and 'mime_type', or None if not found.
    """
    import database
    try:
        async with database.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT audio_data, mime_type FROM voice_notes WHERE id = $1::uuid AND company_id = $2",
                audio_id,
                company_id,
            )
        if row is None:
            logger.warning("Voice note not found — id: %s", audio_id)
            return None
        return {"audio_data": bytes(row["audio_data"]), "mime_type": row["mime_type"]}
    except Exception as exc:
        logger.error(
            "get_voice_note failed — id: %s, error: %s",
            audio_id,
            exc,
            exc_info=True,
        )
        raise
