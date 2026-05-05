"""database.py — public DB API surface; re-exports queries grouped by domain into submodules."""

import asyncpg

from _db_companies import (
    create_pool,
    close_pool,
    get_company_by_phone_number_id,
    _company_cache,
    _COMPANY_CACHE_TTL,
    _MAX_COMPANY_CACHE,
)
from _db_creds import (
    get_company_whatsapp_creds,
    get_company_by_webhook_secret,
    get_webhook_secret_by_company_id,
    get_company_app_url,
    get_app_secret_by_phone_number_id,
)
from _db_orders import lookup_order
from _db_meetings import (
    create_meeting_with_token,
    get_pending_meeting,
    update_meeting_time,
    get_meetings_to_notify,
    mark_link_sent,
)
from _db_voice_notes import store_voice_note, get_voice_note
from _db_contacts import auto_capture_contact
from _db_escalations import create_escalation

# Holds the pool once created by main.py on startup. Mutated by create_pool().
pool: asyncpg.Pool | None = None
