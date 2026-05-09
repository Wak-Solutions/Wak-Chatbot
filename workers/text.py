"""text.py — background worker that turns an inbound text message into a bot reply and persists it."""

import logging

import agent
import memory
import whatsapp
from notifications import mask_phone

logger = logging.getLogger(__name__)


async def process_message(customer_phone: str, message_text: str, company_id: int, creds: dict):
    """Generate and send a bot reply for an inbound text message."""
    real_reply_sent = False
    try:
        logger.info(
            "Processing text message — phone: %s",
            mask_phone(customer_phone),
        )

        reply, meeting_message = await agent.get_reply(
            customer_phone=customer_phone,
            new_message=message_text,
            company_id=company_id,
        )

        await whatsapp.send_message(to=customer_phone, text=reply, token=creds["token"], phone_id=creds["phone_id"])
        real_reply_sent = True
        await memory.save_message(
            customer_phone=customer_phone,
            direction="outbound",
            message_text=reply,
            sender="ai",
            company_id=company_id,
        )
        logger.info(
            "Reply sent — phone: %s, type: text",
            mask_phone(customer_phone),
        )

        if meeting_message:
            await whatsapp.send_message(to=customer_phone, text=meeting_message, token=creds["token"], phone_id=creds["phone_id"])
            await memory.save_message(
                customer_phone=customer_phone,
                direction="outbound",
                message_text=meeting_message,
                sender="ai",
                company_id=company_id,
            )
            logger.info(
                "Meeting invitation sent — phone: %s",
                mask_phone(customer_phone),
            )

    except Exception as exc:
        logger.error(
            "Failed to process text message — phone: %s, error: %s",
            mask_phone(customer_phone),
            exc,
            exc_info=True,
        )
        # Don't leave the customer in silence — send a short generic apology so
        # they know to retry. Wrapped in its own try/except: if Meta is also
        # down, we log and exit cleanly rather than crash the background task.
        # Skip the fallback if the real reply already reached the customer —
        # otherwise a post-send DB failure would deliver a duplicate apology.
        if real_reply_sent:
            return
        try:
            await whatsapp.send_message(
                to=customer_phone,
                text=(
                    "Sorry, something went wrong on our side. "
                    "Please try sending your message again in a moment."
                ),
                token=creds["token"],
                phone_id=creds["phone_id"],
            )
        except Exception as fallback_exc:
            logger.error(
                "Fallback message send failed — phone: %s, error: %s",
                mask_phone(customer_phone),
                fallback_exc,
            )
