"""
whatsapp.py — Meta WhatsApp Cloud API wrapper.
"""

import logging

import httpx

logger = logging.getLogger(__name__)


def _mask_phone(phone: str) -> str:
    if not phone or len(phone) < 4:
        return "****"
    return f"****{phone[-4:]}"


async def send_message(to: str, text: str, *, token: str, phone_id: str) -> None:
    """
    Send a text message via the Meta WhatsApp Cloud API.

    Args:
        to:       Recipient phone in international format without +, e.g. "971501234567".
        text:     Message body. Can include newlines and emoji.
        token:    The company's WhatsApp access token.
        phone_id: The company's WhatsApp phone number ID.

    Raises:
        httpx.HTTPStatusError: If Meta returns a 4xx/5xx response.
    """
    url = f"https://graph.facebook.com/v19.0/{phone_id}/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": text},
    }

    logger.info(
        "[INFO] [whatsapp] Sending message — phone: %s, phone_id: %s",
        _mask_phone(to),
        phone_id,
    )

    async with httpx.AsyncClient() as client:
        response = await client.post(url=url, headers=headers, json=payload, timeout=10.0)

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
