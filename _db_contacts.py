"""_db_contacts.py — contact upsert and per-company linkage on inbound messages."""

import logging

logger = logging.getLogger(__name__)


async def auto_capture_contact(customer_phone: str, company_id: int = 1) -> None:
    """
    Upsert a contact row for a customer who just sent an inbound message,
    then link it to the company via contact_companies.

    contacts has a global UNIQUE (phone_number) constraint — no company_id column.
    The per-company relationship lives in contact_companies (contact_id, company_id).
    """
    import database
    try:
        async with database.pool.acquire() as conn:
            # Step 1: ensure the contact row exists (global, no company scope).
            row = await conn.fetchrow(
                """
                INSERT INTO contacts (phone_number, source)
                VALUES ($1, 'whatsapp')
                ON CONFLICT (phone_number) DO UPDATE SET phone_number = EXCLUDED.phone_number
                RETURNING id
                """,
                customer_phone,
            )
            contact_id = row["id"]

            # Step 2: link to this company (idempotent).
            await conn.execute(
                """
                INSERT INTO contact_companies (contact_id, company_id, source)
                VALUES ($1, $2, 'whatsapp')
                ON CONFLICT (contact_id, company_id) DO NOTHING
                """,
                contact_id,
                company_id,
            )
    except Exception as exc:
        logger.error(
            "auto_capture_contact failed: %s", exc, exc_info=True
        )
        # Non-fatal — don't raise, just log.
