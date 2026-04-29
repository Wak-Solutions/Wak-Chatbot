"""
whatsapp.py — Meta WhatsApp Cloud API wrapper.
"""

import logging

import httpx

from notifications import mask_phone as _mask_phone

logger = logging.getLogger(__name__)

# Shared client injected by main.py lifespan. Falls back to a per-call client
# only when running outside the FastAPI app (e.g. tests).
_http_client: httpx.AsyncClient | None = None


def set_client(client: httpx.AsyncClient) -> None:
    global _http_client
    _http_client = client


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
        "Sending message — phone: %s, phone_id: %s",
        _mask_phone(to),
        phone_id,
    )

    _client = _http_client or httpx.AsyncClient(timeout=10.0)
    _is_temp = _http_client is None
    try:
        response = await _client.post(url=url, headers=headers, json=payload, timeout=10.0)
    finally:
        if _is_temp:
            await _client.aclose()

    if response.is_success:
        logger.info(
            "Message sent — phone: %s, status: %d",
            _mask_phone(to),
            response.status_code,
        )
    else:
        logger.error(
            "Send failed — phone: %s, status: %d, body: %s",
            _mask_phone(to),
            response.status_code,
            response.text[:200],
        )

    response.raise_for_status()
