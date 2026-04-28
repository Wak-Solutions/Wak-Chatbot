"""
notifications.py — fire-and-forget HTTP notifications to the dashboard.

Keeps agent.py and main.py free of cross-service HTTP concerns.
"""

import logging

import httpx

import database
from config import DASHBOARD_URL

logger = logging.getLogger(__name__)


def mask_phone(phone: str) -> str:
    """Return phone number with only last 4 digits visible for safe logging."""
    if not phone or len(phone) < 4:
        return "****"
    return f"****{phone[-4:]}"


async def notify_dashboard(
    event: str,
    customer_phone: str,
    message_text: str,
    escalation_reason: str | None = None,
    company_id: int = 1,
) -> None:
    """
    Notify the dashboard of a new message or human-agent request.
    Fires and forgets — never blocks or crashes the main flow.

    event: "message" | "human_requested"
    """
    try:
        secret = await database.get_webhook_secret_by_company_id(company_id)
        if not secret:
            logger.warning(
                "[WARN] [notifications] No webhook secret for company_id=%d — notification skipped",
                company_id,
            )
            return

        if event == "message":
            url = f"{DASHBOARD_URL}/api/incoming"
            payload = {
                "customer_phone": customer_phone,
                "message_text": message_text,
            }
        elif event == "human_requested":
            url = f"{DASHBOARD_URL}/api/human-requested"
            payload = {
                "customer_phone": customer_phone,
            }
        else:
            logger.warning(
                "[WARN] [notifications] Unknown event type — event: %s", event
            )
            return

        async with httpx.AsyncClient() as client:
            await client.post(
                url=url,
                json=payload,
                headers={"x-webhook-secret": secret},
                timeout=5.0,
            )

        logger.info(
            "[INFO] [notifications] Dashboard notified — event: %s, phone: %s",
            event,
            mask_phone(customer_phone),
        )

    except Exception as exc:
        # Never let a notification failure crash the message flow.
        logger.warning(
            "[WARN] [notifications] Dashboard notification failed — event: %s, phone: %s, error: %s",
            event,
            mask_phone(customer_phone),
            exc,
        )
