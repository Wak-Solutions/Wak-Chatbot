"""
test_webhook.py — Tests for GET /webhook (verification) and POST /webhook (messages).
"""

import json
from unittest.mock import AsyncMock, patch

import pytest

from tests.conftest import make_audio_webhook_payload, make_signature, make_text_webhook_payload


class TestWebhookVerification:
    """GET /webhook — Meta hub verification handshake."""

    async def test_valid_verify_token_returns_challenge(self, client):
        resp = await client.get(
            "/webhook",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": "test-verify-token",
                "hub.challenge": "abc123",
            },
        )
        assert resp.status_code == 200
        assert resp.text == "abc123"

    async def test_wrong_verify_token_returns_403(self, client):
        resp = await client.get(
            "/webhook",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": "wrong-token",
                "hub.challenge": "abc123",
            },
        )
        assert resp.status_code == 403

    async def test_missing_token_returns_403(self, client):
        resp = await client.get("/webhook", params={"hub.mode": "subscribe"})
        assert resp.status_code == 403


class TestWebhookIncomingMessages:
    """POST /webhook — inbound message handling with HMAC signature verification."""

    async def test_missing_signature_returns_403(self, client):
        body = make_text_webhook_payload("971501234567", "hello")
        resp = await client.post(
            "/webhook",
            content=body,
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 403

    async def test_wrong_signature_returns_403(self, client):
        body = make_text_webhook_payload("971501234567", "hello")
        resp = await client.post(
            "/webhook",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": "sha256=badhash",
            },
        )
        assert resp.status_code == 403

    async def test_valid_text_message_returns_200(self, client, mock_conn):
        """Valid signature + text message → 200 returned immediately."""
        body = make_text_webhook_payload("971501234567", "hello")
        sig = make_signature(body)

        with (
            patch("database.get_app_secret_by_phone_number_id",
                  new=AsyncMock(return_value="test-app-secret-32chars-padding000")),
            patch("database.get_company_by_phone_number_id", new=AsyncMock(return_value=1)),
            patch("database.get_company_whatsapp_creds",
                  new=AsyncMock(return_value={"token": "t", "phone_id": "1234567890", "app_secret": "s"})),
            patch("agent.get_reply", new=AsyncMock(return_value=("Hi there!", None))),
            patch("whatsapp.send_message", new=AsyncMock()),
            patch("memory.save_message", new=AsyncMock()),
        ):
            resp = await client.post(
                "/webhook",
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Hub-Signature-256": sig,
                },
            )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    async def test_valid_audio_message_returns_200(self, client, mock_conn):
        """Valid signature + audio message → 200 returned immediately."""
        body = make_audio_webhook_payload("971501234567")
        sig = make_signature(body)

        with (
            patch("database.get_app_secret_by_phone_number_id",
                  new=AsyncMock(return_value="test-app-secret-32chars-padding000")),
            patch("database.get_company_by_phone_number_id", new=AsyncMock(return_value=1)),
            patch("database.get_company_whatsapp_creds",
                  new=AsyncMock(return_value={"token": "t", "phone_id": "1234567890", "app_secret": "s"})),
            patch("transcribe.download_media", new=AsyncMock(return_value=(b"audio", "audio/ogg"))),
            patch("transcribe.transcribe", new=AsyncMock(return_value="hello")),
            patch("database.store_voice_note", new=AsyncMock(return_value="uuid-123")),
            patch("agent.get_reply", new=AsyncMock(return_value=("Hi!", None))),
            patch("whatsapp.send_message", new=AsyncMock()),
            patch("memory.save_message", new=AsyncMock()),
        ):
            resp = await client.post(
                "/webhook",
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Hub-Signature-256": sig,
                },
            )
        assert resp.status_code == 200

    async def test_status_update_payload_returns_200(self, client):
        """Webhook payload with no 'messages' key (e.g. delivery receipt) → 200."""
        payload = {"entry": [{"changes": [{"value": {"metadata": {"phone_number_id": "x"}}}]}]}
        body = json.dumps(payload).encode()
        sig = make_signature(body)
        with patch(
            "database.get_app_secret_by_phone_number_id",
            new=AsyncMock(return_value="test-app-secret-32chars-padding000"),
        ):
            resp = await client.post(
                "/webhook",
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Hub-Signature-256": sig,
                },
            )
        assert resp.status_code == 200

    async def test_tampered_body_wrong_sig(self, client):
        """Signing one body but sending another → 403."""
        original_body = make_text_webhook_payload("971501234567", "hello")
        tampered_body = make_text_webhook_payload("971501234567", "HACKED")
        sig = make_signature(original_body)
        resp = await client.post(
            "/webhook",
            content=tampered_body,
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": sig,
            },
        )
        assert resp.status_code == 403
