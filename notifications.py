"""
notifications.py — fire-and-forget HTTP notifications to the dashboard.

Keeps agent.py and main.py free of cross-service HTTP concerns.
"""

import logging

import httpx

from config import DASHBOARD_URL, WEBHOOK_SECRET

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
    Notify the dashboard of a new message or escalation.
    Fires and forgets — never blocks or crashes the main flow.

    event: "message" or "escalation"
    """
    try:
        if event == "message":
            url = f"{DASHBOARD_URL}/api/incoming"
            payload = {
                "customer_phone": customer_phone,
                "message_text": message_text,
                "company_id": company_id,
            }
        elif event == "escalation":
            url = f"{DASHBOARD_URL}/api/escalate"
            payload = {
                "customer_phone": customer_phone,
                "escalation_reason": escalation_reason,
                "company_id": company_id,
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
                headers={"x-webhook-secret": WEBHOOK_SECRET},
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
