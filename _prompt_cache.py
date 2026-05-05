"""_prompt_cache.py — DB-backed system prompt loader with a 60-second TTL cache per company."""

import logging
import time as _time

import database
from _prompt_default import DEFAULT_SYSTEM_PROMPT
from _prompt_language import _LANGUAGE_OVERRIDE, detect_language

logger = logging.getLogger(__name__)

# Per-company prompt cache: company_id → (prompt, timestamp)
_cache: dict[int, tuple[str, float]] = {}
_CACHE_TTL: float = 60.0  # seconds


async def get_system_prompt(company_id: int = 1, current_message: str = "") -> str:
    """Return the active system prompt for company_id with a 60-second TTL cache.

    If current_message is provided, appends a language override instruction so
    the model replies in the language of the current message rather than being
    misled by prior turns in a different language.
    """
    global _cache
    now = _time.monotonic()
    cached = _cache.get(company_id)
    if cached is not None and (now - cached[1]) < _CACHE_TTL:
        prompt = cached[0]
    else:
        try:
            async with database.pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT system_prompt FROM chatbot_config WHERE company_id = $1 ORDER BY id LIMIT 1",
                    company_id,
                )
            if row and row["system_prompt"]:
                _cache[company_id] = (row["system_prompt"], now)
                logger.info(
                    "System prompt refreshed from database — company_id: %d",
                    company_id,
                )
                prompt = _cache[company_id][0]
            else:
                raise ValueError("no system_prompt row")
        except Exception as exc:
            logger.warning(
                "Could not load system prompt from DB — using cached/default: %s",
                exc,
            )
            prompt = cached[0] if cached is not None else DEFAULT_SYSTEM_PROMPT
            if cached is None:
                logger.info("Using hardcoded default system prompt — company_id: %d", company_id)

    if current_message.strip():
        lang = detect_language(current_message)
        if lang:
            prompt = prompt + _LANGUAGE_OVERRIDE.format(language=lang)

    return prompt


def invalidate_prompt_cache(company_id: int | None = None) -> None:
    """Force the next get_system_prompt() call to reload from the database.

    Pass company_id to invalidate only that company's cache, or None to clear all.
    """
    global _cache
    if company_id is not None:
        _cache.pop(company_id, None)
        logger.info("Prompt cache invalidated — company_id: %d", company_id)
    else:
        _cache.clear()
        logger.info("Prompt cache fully invalidated")
