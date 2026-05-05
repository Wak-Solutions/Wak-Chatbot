"""link_delivery.py — background loop that sends Jitsi links 15 minutes before scheduled meetings."""

import asyncio
import logging

import database
import whatsapp
from notifications import mask_phone

logger = logging.getLogger(__name__)


async def _link_delivery_loop():
    """
    Background task that runs every 60 seconds.
    Sends meeting links to customers whose meetings start within 15 minutes.
    """
    while True:
        await asyncio.sleep(60)
        try:
            meetings = await database.get_meetings_to_notify()
            for m in meetings:
                app_url = await database.get_company_app_url(m["company_id"])
                if app_url is None:
                    logger.error(
                        "Link delivery — app_url not set for company %d, skipping",
                        m["company_id"],
                    )
                    continue
                meeting_url = (
                    f"{app_url}/meeting/{m['meeting_token']}"
                    if m.get("meeting_token")
                    else m["meeting_link"]
                )
                msg = f"Your meeting is starting soon! Join here: {meeting_url}"
                _creds = await database.get_company_whatsapp_creds(m["company_id"])
                if _creds is None:
                    logger.error(
                        "Link delivery — company %d has no WhatsApp creds, skipping",
                        m["company_id"],
                    )
                    continue
                await whatsapp.send_message(to=m["customer_phone"], text=msg, token=_creds["token"], phone_id=_creds["phone_id"])
                await database.mark_link_sent(m["id"])
                logger.info(
                    "Meeting link sent — phone: %s, meeting_id: %s",
                    mask_phone(m["customer_phone"]),
                    m["id"],
                )
        except Exception as exc:
            logger.error("Link delivery job error: %s", exc, exc_info=True)
