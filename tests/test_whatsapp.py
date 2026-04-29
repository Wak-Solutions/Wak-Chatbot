"""
test_whatsapp.py — Tests for whatsapp.py (Meta WhatsApp Cloud API wrapper).
"""

from unittest.mock import AsyncMock, MagicMock

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


def _make_mock_client(mock_resp):
    """Inject a shared AsyncMock client into whatsapp module."""
    mock_client = MagicMock(spec=httpx.AsyncClient)
    mock_client.post = AsyncMock(return_value=mock_resp)
    mock_client.aclose = AsyncMock()
    whatsapp.set_client(mock_client)
    return mock_client


@pytest.fixture(autouse=True)
def reset_whatsapp_client():
    """Reset the shared client after each test so tests don't bleed state."""
    yield
    whatsapp.set_client(None)  # type: ignore[arg-type]


class TestSendMessage:
    async def test_posts_to_correct_url(self):
        """Requests must go to the Meta Graph API URL containing WHATSAPP_PHONE_ID."""
        mock_client = _make_mock_client(_make_mock_response(200))
        await whatsapp.send_message(to="971501234567", text="Hello", token="test-wa-token", phone_id="1234567890")
        call_kwargs = mock_client.post.call_args
        url = call_kwargs.kwargs.get("url") or call_kwargs.args[0]
        assert "1234567890" in url
        assert "messages" in url

    async def test_payload_structure(self):
        """The JSON payload must match the Meta Cloud API spec."""
        mock_client = _make_mock_client(_make_mock_response(200))
        await whatsapp.send_message(to="971501234567", text="Test message", token="test-wa-token", phone_id="1234567890")
        payload = mock_client.post.call_args.kwargs["json"]
        assert payload["messaging_product"] == "whatsapp"
        assert payload["to"] == "971501234567"
        assert payload["type"] == "text"
        assert payload["text"]["body"] == "Test message"

    async def test_authorization_header_sent(self):
        """Bearer token must be included in the Authorization header."""
        mock_client = _make_mock_client(_make_mock_response(200))
        await whatsapp.send_message(to="971501234567", text="Hi", token="test-wa-token", phone_id="1234567890")
        headers = mock_client.post.call_args.kwargs["headers"]
        assert "Authorization" in headers
        assert "Bearer" in headers["Authorization"]

    async def test_raises_on_4xx_response(self):
        """A 4xx response from Meta must propagate as HTTPStatusError."""
        _make_mock_client(_make_mock_response(401))
        with pytest.raises(httpx.HTTPStatusError):
            await whatsapp.send_message(to="971501234567", text="Hi", token="test-wa-token", phone_id="1234567890")

    async def test_succeeds_silently_on_200(self):
        """A 200 response must return None without raising."""
        _make_mock_client(_make_mock_response(200))
        result = await whatsapp.send_message(to="971501234567", text="Hi", token="test-wa-token", phone_id="1234567890")
        assert result is None
