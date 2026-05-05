"""_agent_booking.py — resolve or create per-customer booking URLs with advisory locking."""

import logging

import httpx

import database
from config import DASHBOARD_URL
from notifications import mask_phone
from _agent_utils import get_http_client

logger = logging.getLogger(__name__)


async def _resolve_booking_url(
    customer_phone: str,
    pending_meeting: dict | None,
    company_id: int,
) -> str | None:
    """
    Return a booking URL for the customer.

    Reuses an existing unbooked meeting token if one exists, otherwise
    creates a fresh token via the dashboard API. Returns None on failure.
    """
    # Use a Postgres advisory lock keyed on (company_id, customer_phone) to
    # prevent two concurrent webhook deliveries from both creating a token.
    # SELECT FOR UPDATE only locks existing rows — it does not prevent a race
    # when the result set is empty. pg_try_advisory_xact_lock is non-blocking:
    # if another instance holds the lock, we re-query for its token instead.
    conn = await database.pool.acquire()
    try:
        async with conn.transaction():
            lock_key = hash((company_id, customer_phone)) & 0x7FFFFFFFFFFFFFFF
            acquired = await conn.fetchval(
                "SELECT pg_try_advisory_xact_lock($1)", lock_key
            )
            if not acquired:
                # Another instance is mid-creation — return its token if ready.
                row = await conn.fetchrow(
                    """
                    SELECT meeting_token FROM meetings
                    WHERE customer_phone = $1
                      AND company_id     = $2
                      AND status         = 'pending'
                      AND scheduled_at   IS NULL
                      AND created_at     >= NOW() - INTERVAL '5 minutes'
                    ORDER BY created_at DESC LIMIT 1
                    """,
                    customer_phone,
                    company_id,
                )
                if row and row["meeting_token"]:
                    logger.info(
                        "Advisory lock missed — reusing token — phone: %s",
                        mask_phone(customer_phone),
                    )
                    return f"{DASHBOARD_URL}/book/{row['meeting_token']}"
                return None

            # Lock acquired — check for an existing token first.
            row = await conn.fetchrow(
                """
                SELECT meeting_token FROM meetings
                WHERE customer_phone = $1
                  AND company_id     = $2
                  AND status         = 'pending'
                  AND scheduled_at   IS NULL
                  AND created_at     >= NOW() - INTERVAL '5 minutes'
                ORDER BY created_at DESC LIMIT 1
                """,
                customer_phone,
                company_id,
            )
            if row and row["meeting_token"]:
                logger.info(
                    "Reusing existing meeting token — phone: %s",
                    mask_phone(customer_phone),
                )
                return f"{DASHBOARD_URL}/book/{row['meeting_token']}"

            # No existing token — create one now.
            try:
                secret = await database.get_webhook_secret_by_company_id(company_id)
                if not secret:
                    logger.error(
                        "create-token — no webhook secret for company_id=%d",
                        company_id,
                    )
                    return None
                _http = get_http_client() or httpx.AsyncClient(timeout=10.0)
                _is_temp = get_http_client() is None
                try:
                    resp = await _http.post(
                        f"{DASHBOARD_URL}/api/meetings/create-token",
                        json={"customer_phone": customer_phone},
                        headers={"x-webhook-secret": secret},
                        timeout=10.0,
                    )
                    resp.raise_for_status()
                    token = resp.json()["token"]
                    logger.info(
                        "Meeting token created — phone: %s",
                        mask_phone(customer_phone),
                    )
                    return f"{DASHBOARD_URL}/book/{token}"
                finally:
                    if _is_temp:
                        await _http.aclose()
            except Exception as exc:
                logger.error(
                    "create-token failed — phone: %s, error: %s",
                    mask_phone(customer_phone),
                    exc,
                )
                return None
    finally:
        try:
            await database.pool.release(conn)
        except Exception as e:
            logger.error("Failed to release connection: %s", e)
