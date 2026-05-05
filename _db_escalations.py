"""_db_escalations.py — escalation creation queries."""

import logging

logger = logging.getLogger(__name__)


async def create_escalation(customer_phone: str, escalation_reason: str, company_id: int = 1) -> None:
    """
    Inserts an open escalation for a customer, scoped to company_id.
    Skips insert if an open escalation already exists for the same phone+company.
    """
    import database
    try:
        async with database.pool.acquire() as conn:
            existing = await conn.fetchval(
                """
                SELECT id FROM escalations
                WHERE customer_phone = $1 AND company_id = $2 AND status = 'open'
                LIMIT 1
                """,
                customer_phone,
                company_id,
            )
            if existing is None:
                await conn.execute(
                    """
                    INSERT INTO escalations (customer_phone, escalation_reason, status, company_id, created_at)
                    VALUES ($1, $2, 'open', $3, NOW())
                    """,
                    customer_phone,
                    escalation_reason,
                    company_id,
                )
                logger.info("Escalation created — company_id: %d", company_id)
            else:
                logger.info("Escalation already open, skipping insert — company_id: %d", company_id)
    except Exception as exc:
        logger.error("create_escalation failed: %s", exc, exc_info=True)
        raise
