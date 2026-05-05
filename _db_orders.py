"""_db_orders.py — order lookup queries."""

import logging

logger = logging.getLogger(__name__)


async def lookup_order(order_number: str, company_id: int = 1) -> dict:
    """
    Query the orders table for a given order_number scoped to company_id.
    Called by agent.py when OpenAI triggers the lookup_order tool.
    """
    import database
    try:
        async with database.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT order_number, status, details, created_at
                FROM orders
                WHERE order_number = $1 AND company_id = $2
                """,
                order_number,
                company_id,
            )
        if row is None:
            logger.info("Order not found — order_number: %s", order_number)
            return {"found": False, "message": f"No order found with number {order_number}."}
        logger.info(
            "Order lookup success — order_number: %s, status: %s",
            order_number,
            row["status"],
        )
        return {
            "found": True,
            "order_number": row["order_number"],
            "status": row["status"],
            "details": row["details"],
            "created_at": str(row["created_at"]),
        }
    except Exception as exc:
        logger.error(
            "lookup_order failed — order_number: %s, error: %s",
            order_number,
            exc,
            exc_info=True,
        )
        raise
