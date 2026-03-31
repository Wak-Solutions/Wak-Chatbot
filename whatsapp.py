"""
whatsapp.py — Meta WhatsApp Cloud API wrapper.
"""

import logging

import httpx

from config import WHATSAPP_PHONE_ID, WHATSAPP_TOKEN

logger = logging.getLogger(__name__)

WHATSAPP_API_URL = (
    f"https://graph.facebook.com/v19.0/{WHATSAPP_PHONE_ID}/messages"
)

HEADERS = {
    "Authorization": f"Bearer {WHATSAPP_TOKEN}",
    "Content-Type": "application/json",
}


def _mask_phone(phone: str) -> str:
    if not phone or len(phone) < 4:
        return "****"
    return f"****{phone[-4:]}"


async def send_message(to: str, text: str) -> None:
    """
    Send a text message via the Meta WhatsApp Cloud API.

    Args:
        to:   Recipient phone in international format without +, e.g. "971501234567".
        text: Message body. Can include newlines and emoji.

    Raises:
        httpx.HTTPStatusError: If Meta returns a 4xx/5xx response.
    """
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": text},
    }

    logger.info(
        "[INFO] [whatsapp] Sending message — phone: %s, type: text",
        _mask_phone(to),
    )

    async with httpx.AsyncClient() as client:
        response = await client.post(
            url=WHATSAPP_API_URL,
            headers=HEADERS,
            json=payload,
            timeout=10.0,
        )

    if response.is_success:
        logger.info(
            "[INFO] [whatsapp] Message sent — phone: %s, status: %d",
            _mask_phone(to),
            response.status_code,
        )
    else:
        logger.error(
            "[ERROR] [whatsapp] Send failed — phone: %s, status: %d, body: %s",
            _mask_phone(to),
            response.status_code,
            response.text[:200],
        )

    response.raise_for_status()
