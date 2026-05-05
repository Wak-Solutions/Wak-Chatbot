"""
test_endpoints.py — Auth, validation, and success-path tests for:
  POST /send, POST /api/send-email, GET /audio/{audio_id}
"""

import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

GOOD_SECRET = "test-webhook-secret"
BAD_SECRET = "wrong-secret"
VALID_UUID = str(uuid.uuid4())

# Company row returned when GOOD_SECRET is presented
GOOD_COMPANY = {"id": 1, "name": "Test Co"}
INVALID_UUID = "not-a-uuid"


# ---------------------------------------------------------------------------
# POST /send
# ---------------------------------------------------------------------------


class TestSendEndpoint:
    async def test_missing_secret_returns_403(self, client):
        resp = await client.post("/send", json={"customer_phone": "971501234567", "message": "hi", "company_id": 1})
        assert resp.status_code == 403

    async def test_wrong_secret_returns_403(self, client):
        resp = await client.post(
            "/send",
            json={"customer_phone": "971501234567", "message": "hi", "company_id": 1},
            headers={"x-webhook-secret": BAD_SECRET},
        )
        assert resp.status_code == 403

    async def test_missing_company_id_returns_400(self, client):
        # /send now resolves company from the secret — missing phone/message → 400
        with patch("database.get_company_by_webhook_secret",
                   new=AsyncMock(return_value=GOOD_COMPANY)):
            resp = await client.post(
                "/send",
                json={"message": "hi"},
                headers={"x-webhook-secret": GOOD_SECRET},
            )
        assert resp.status_code == 400

    async def test_valid_request_returns_200(self, client):
        with (
            patch("database.get_company_by_webhook_secret",
                  new=AsyncMock(return_value=GOOD_COMPANY)),
            patch("database.get_company_whatsapp_creds",
                  new=AsyncMock(return_value={"token": "t", "phone_id": "p"})),
            patch("whatsapp.send_message", new=AsyncMock()),
            patch("memory.save_message", new=AsyncMock()),
        ):
            resp = await client.post(
                "/send",
                json={"customer_phone": "971501234567", "message": "hi"},
                headers={"x-webhook-secret": GOOD_SECRET},
            )
        assert resp.status_code == 200
        assert resp.json()["status"] == "sent"

    async def test_missing_phone_or_message_returns_400(self, client):
        with patch("database.get_company_by_webhook_secret",
                   new=AsyncMock(return_value=GOOD_COMPANY)):
            resp = await client.post(
                "/send",
                json={},
                headers={"x-webhook-secret": GOOD_SECRET},
            )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# GET /audio/{audio_id}
# ---------------------------------------------------------------------------


class TestAudioEndpoint:
    async def test_missing_secret_returns_403(self, client):
        resp = await client.get(f"/audio/{VALID_UUID}")
        assert resp.status_code == 403

    async def test_wrong_secret_returns_403(self, client):
        resp = await client.get(f"/audio/{VALID_UUID}", headers={"x-webhook-secret": BAD_SECRET})
        assert resp.status_code == 403

    async def test_invalid_uuid_returns_404(self, client):
        resp = await client.get(
            f"/audio/{INVALID_UUID}",
            headers={"x-webhook-secret": GOOD_SECRET},
        )
        assert resp.status_code == 404

    async def test_unknown_uuid_returns_404(self, client):
        with patch("database.get_voice_note", new=AsyncMock(return_value=None)):
            resp = await client.get(
                f"/audio/{VALID_UUID}",
                headers={"x-webhook-secret": GOOD_SECRET},
            )
        assert resp.status_code == 404

    async def test_valid_uuid_returns_audio(self, client):
        row = {"audio_data": b"FAKEAUDIO", "mime_type": "audio/ogg"}
        with (
            patch("database.get_company_by_webhook_secret",
                  new=AsyncMock(return_value=GOOD_COMPANY)),
            patch("database.get_voice_note", new=AsyncMock(return_value=row)),
        ):
            resp = await client.get(
                f"/audio/{VALID_UUID}",
                headers={"x-webhook-secret": GOOD_SECRET},
            )
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("audio/ogg")
        assert resp.content == b"FAKEAUDIO"
