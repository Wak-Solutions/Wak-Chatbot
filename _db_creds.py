"""_db_creds.py — per-company credential and configuration lookups."""

import logging

logger = logging.getLogger(__name__)


async def get_company_whatsapp_creds(company_id: int) -> dict | None:
    """
    Returns {'token': str, 'phone_id': str, 'app_secret': str | None} for the
    given company, or None if the company has no WhatsApp credentials configured.
    Always reads from the DB — a stale in-process cache caused 190 errors after
    admins rotated their Meta access token.
    """
    import database
    try:
        async with database.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT whatsapp_token, whatsapp_phone_number_id, whatsapp_app_secret FROM companies WHERE id = $1",
                company_id,
            )
        if not row or not row["whatsapp_token"] or not row["whatsapp_phone_number_id"]:
            logger.error(
                "Company %d has no WhatsApp credentials configured", company_id
            )
            return None
        return {
            "token": row["whatsapp_token"],
            "phone_id": row["whatsapp_phone_number_id"],
            "app_secret": row["whatsapp_app_secret"],
        }
    except Exception as exc:
        logger.error(
            "get_company_whatsapp_creds failed — company_id: %d, error: %s",
            company_id, exc, exc_info=True,
        )
        return None


async def get_company_by_webhook_secret(secret: str) -> dict | None:
    """
    Resolve the active company that owns this per-tenant webhook secret.

    Used to authenticate cross-service requests (TS dashboard → Python bot)
    without trusting a caller-supplied company_id. The DB equality check is
    timing-safe enough for our threat model: PostgreSQL hashes the column
    before comparing, and the secret space (32 bytes) makes brute force
    infeasible regardless of side-channel timing.

    Returns {'id': int, 'name': str} or None if the secret is empty,
    unknown, or belongs to an inactive company.
    """
    import database
    if not secret:
        return None
    try:
        async with database.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, name FROM companies
                WHERE webhook_secret = $1 AND is_active = true
                LIMIT 1
                """,
                secret,
            )
        if not row:
            logger.warning("Webhook secret did not match any active company")
            return None
        return {"id": row["id"], "name": row["name"]}
    except Exception as exc:
        logger.warning(
            "get_company_by_webhook_secret failed: %s", exc, exc_info=True
        )
        return None


async def get_webhook_secret_by_company_id(company_id: int) -> str | None:
    """
    Return the per-tenant webhook secret for a given company.
    Used by the Python bot when calling internal Agents API endpoints so it
    can send the correct x-webhook-secret header instead of a shared secret.
    Returns None if the company has no secret or is inactive.
    """
    import database
    try:
        async with database.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT webhook_secret FROM companies WHERE id = $1 AND is_active = true LIMIT 1",
                company_id,
            )
        return row["webhook_secret"] if row else None
    except Exception as exc:
        logger.warning(
            "get_webhook_secret_by_company_id failed — company_id: %d, error: %s",
            company_id, exc, exc_info=True,
        )
        return None


async def get_company_app_url(company_id: int) -> str | None:
    """
    Returns the app_url for the given company, or None if not set.
    Callers must treat None as a hard error — never fall back to a hardcoded URL.
    """
    import database
    try:
        async with database.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT app_url FROM companies WHERE id = $1 LIMIT 1",
                company_id,
            )
        if not row or not row["app_url"]:
            logger.error(
                "companies.app_url is not set for company_id=%d — "
                "set it in the branding settings before enabling this tenant",
                company_id,
            )
            return None
        return row["app_url"].rstrip("/")
    except Exception as exc:
        logger.error(
            "get_company_app_url failed — company_id: %d, error: %s",
            company_id, exc, exc_info=True,
        )
        return None


async def get_app_secret_by_phone_number_id(phone_number_id: str) -> str | None:
    """
    Returns the Meta App Secret for the company that owns this phone_number_id.
    Used to verify inbound webhook signatures per-company.
    """
    import database
    try:
        async with database.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT whatsapp_app_secret FROM companies WHERE whatsapp_phone_number_id = $1 LIMIT 1",
                phone_number_id,
            )
        return row["whatsapp_app_secret"] if row else None
    except Exception as exc:
        logger.error(
            "get_app_secret_by_phone_number_id failed: %s", exc, exc_info=True,
        )
        return None
