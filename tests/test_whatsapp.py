"""
test_whatsapp.py — Tests for whatsapp.py (Meta WhatsApp Cloud API wrapper).
"""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

import whatsapp


def _make_mock_response(status_code: int = 200, json_data: dict | None = None):
    """Create a mock httpx.Response."""
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = status_code
    mock_resp.is_success = status_code < 400
    mock_resp.text = ""
    mock_resp.json.return_value = json_data or {"messages": [{"id": "wamid.abc"}]}
    if not mock_resp.is_success:
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            message="Bad request",
            request=MagicMock(),
            response=mock_resp,
        )
    else:
        mock_resp.raise_for_status = MagicMock(return_value=None)
    return mock_resp


class TestSendMessage:
    async def test_posts_to_correct_url(self):
        """Requests must go to the Meta Graph API URL containing WHATSAPP_PHONE_ID."""
        mock_resp = _make_mock_response(200)
        with patch("httpx.AsyncClient") as MockClient:
            instance = MockClient.return_value.__aenter__.return_value
            instance.post = AsyncMock(return_value=mock_resp)
            await whatsapp.send_message(to="971501234567", text="Hello")
        call_kwargs = instance.post.call_args
        url = call_kwargs.kwargs.get("url") or call_kwargs.args[0]
        assert "1234567890" in url  # WHATSAPP_PHONE_ID from env
        assert "messages" in url

    async def test_payload_structure(self):
        """The JSON payload must match the Meta Cloud API spec."""
        mock_resp = _make_mock_response(200)
        with patch("httpx.AsyncClient") as MockClient:
            instance = MockClient.return_value.__aenter__.return_value
            instance.post = AsyncMock(return_value=mock_resp)
            await whatsapp.send_message(to="971501234567", text="Test message")
        payload = instance.post.call_args.kwargs["json"]
        assert payload["messaging_product"] == "whatsapp"
        assert payload["to"] == "971501234567"
        assert payload["type"] == "text"
        assert payload["text"]["body"] == "Test message"

    async def test_authorization_header_sent(self):
        """Bearer token must be included in the Authorization header."""
        mock_resp = _make_mock_response(200)
        with patch("httpx.AsyncClient") as MockClient:
            instance = MockClient.return_value.__aenter__.return_value
            instance.post = AsyncMock(return_value=mock_resp)
            await whatsapp.send_message(to="971501234567", text="Hi")
        headers = instance.post.call_args.kwargs["headers"]
        assert "Authorization" in headers
        assert "Bearer" in headers["Authorization"]

    async def test_raises_on_4xx_response(self):
        """A 4xx response from Meta must propagate as HTTPStatusError."""
        mock_resp = _make_mock_response(401)
        with patch("httpx.AsyncClient") as MockClient:
            instance = MockClient.return_value.__aenter__.return_value
            instance.post = AsyncMock(return_value=mock_resp)
            with pytest.raises(httpx.HTTPStatusError):
                await whatsapp.send_message(to="971501234567", text="Hi")

    async def test_succeeds_silently_on_200(self):
        """A 200 response must return None without raising."""
        mock_resp = _make_mock_response(200)
        with patch("httpx.AsyncClient") as MockClient:
            instance = MockClient.return_value.__aenter__.return_value
            instance.post = AsyncMock(return_value=mock_resp)
            result = await whatsapp.send_message(to="971501234567", text="Hi")
        assert result is None
