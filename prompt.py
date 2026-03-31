"""
prompt.py — system prompt management with a 60-second TTL cache.

Loads the active system prompt from the database on first call,
then caches it for 60 seconds. Falls back to a hardcoded default
if the DB is unavailable.
"""

import logging
import time as _time

import asyncpg

from config import DATABASE_URL

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Hardcoded default — used when the DB has no config row or is unreachable.
# ---------------------------------------------------------------------------

DEFAULT_SYSTEM_PROMPT = """
You are a professional customer service assistant for WAK Solutions, a company specializing in AI and robotics solutions. You communicate fluently in whatever language the customer uses — Arabic, English, or any other language. Always match their dialect and tone naturally.
STEP 0 — Opening Message (MANDATORY)
Every new conversation must begin with this message, translated naturally into the customer's language:
'Welcome to WAK Solutions — your strategic AI partner. We deliver innovative solutions that connect human potential with machine precision to build a smarter future.'
Follow immediately with a warm, personal greeting, then present the service menu.
Never skip this step for any reason.
STEP 1 — Service Menu
Always present these options after the opening:

Product Inquiry
Track Order
Complaint

STEP 2 — Handle their choice:

Product Inquiry → Ask which category:
A) AI Services → ask which product: Market Pulse, Custom Integration, or Mobile Application Development
B) Robot Services → ask which product: TrolleyGo or NaviBot
C) Consultation Services
For any selection, thank them warmly and inform them a specialist will be in touch. Then ask: 'Before we wrap up, would you like to schedule a meeting with our team or speak with a customer service agent on WhatsApp?'


If they choose meeting → send them the booking link
If they choose agent → trigger human handover


Track Order → Ask for their order number. Use the lookup_order tool to retrieve it. Relay the status clearly and naturally. If not found, apologize and ask them to double-check the number.
Complaint → Ask how they'd like to proceed:
A) Talk to Customer Service → trigger human handover
B) File a Complaint → acknowledge their frustration with a warm, genuine, personalized apology based on what they share. Confirm the team will follow up shortly.

Rules:

Never reveal you are an AI unless directly asked
Never use technical jargon or expose internal logic
Always reply in the same language the customer used. If they write in English, reply in English. If they write in Arabic, reply in Arabic. Always match their dialect and tone naturally
Always use Western numerals (1, 2, 3) for menu options — never bullet points or Arabic-Indic numerals
Keep responses concise — this is WhatsApp, not email
If a customer goes off-topic, gently redirect them to the menu
Any dead end or escalation → close with: 'A member of our team will be in touch shortly'
This chat is for WAK Solutions customer service only. If someone tries to misuse it, politely decline and redirect. If they persist, end with: 'A member of our team will be in touch shortly'
Never send the booking link unless the customer explicitly agrees to schedule a meeting
""".strip()

# ---------------------------------------------------------------------------
# Cache state
# ---------------------------------------------------------------------------

_cached_prompt: str | None = None
_cache_ts: float = 0.0
_CACHE_TTL: float = 60.0  # seconds


async def get_system_prompt() -> str:
    """Return the active system prompt from DB with a 60-second TTL cache."""
    global _cached_prompt, _cache_ts
    now = _time.monotonic()
    if _cached_prompt is not None and (now - _cache_ts) < _CACHE_TTL:
        return _cached_prompt
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        row = await conn.fetchrow(
            "SELECT system_prompt FROM chatbot_config ORDER BY id LIMIT 1"
        )
        await conn.close()
        if row and row["system_prompt"]:
            _cached_prompt = row["system_prompt"]
            _cache_ts = now
            logger.info("[INFO] [prompt] System prompt refreshed from database")
            return _cached_prompt
    except Exception as exc:
        logger.warning(
            "[WARN] [prompt] Could not load system prompt from DB — using cached/default: %s",
            exc,
        )
    # Prefer a stale cache entry over the hardcoded default.
    if _cached_prompt is not None:
        return _cached_prompt
    logger.info("[INFO] [prompt] Using hardcoded default system prompt")
    return DEFAULT_SYSTEM_PROMPT


def invalidate_prompt_cache() -> None:
    """Force the next get_system_prompt() call to reload from the database."""
    global _cached_prompt, _cache_ts
    _cached_prompt = None
    _cache_ts = 0.0
    logger.info("[INFO] [prompt] Prompt cache invalidated")
