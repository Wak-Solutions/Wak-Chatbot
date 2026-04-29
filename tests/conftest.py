"""
conftest.py — shared fixtures and environment setup for all chatbot tests.

IMPORTANT: Environment variables must be set BEFORE any module from the chatbot
package is imported, because config.py raises EnvironmentError at import time
if required vars are missing.
"""

import hashlib
import hmac
import json
import os
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest

# ── Set required env vars before any chatbot imports ─────────────────────────
os.environ.setdefault("OPENAI_API_KEY", "sk-test-key-00000000000000000000000000000000")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/testdb")
os.environ.setdefault("WHATSAPP_TOKEN", "test-wa-token")
os.environ.setdefault("WHATSAPP_PHONE_ID", "1234567890")
os.environ.setdefault("VERIFY_TOKEN", "test-verify-token")
os.environ.setdefault("DASHBOARD_URL", "http://localhost:5000")
os.environ.setdefault("WEBHOOK_SECRET", "test-webhook-secret")
os.environ.setdefault("WHATSAPP_APP_SECRET", "test-app-secret-32chars-padding000")

# ── Now safe to import chatbot modules ────────────────────────────────────────
import database  # noqa: E402


# ── Database mock helpers ─────────────────────────────────────────────────────


@pytest.fixture
def mock_conn():
    """A mock asyncpg connection that satisfies all common query patterns."""
    conn = AsyncMock()
    conn.fetchval.return_value = 1
    conn.fetchrow.return_value = None
    conn.fetch.return_value = []
    conn.execute.return_value = "OK"
    # transaction() in asyncpg is a synchronous call that returns an async CM.
    # Use MagicMock (not AsyncMock) so calling it doesn't produce a coroutine.
    _txn = MagicMock()
    _txn.__aenter__ = AsyncMock(return_value=None)
    _txn.__aexit__ = AsyncMock(return_value=False)
    conn.transaction = MagicMock(return_value=_txn)
    return conn


@pytest.fixture
def mock_pool(mock_conn):
    """A mock asyncpg Pool whose .acquire() is an async context manager."""
    pool = MagicMock()

    @asynccontextmanager
    async def fake_acquire():
        yield mock_conn

    pool.acquire = fake_acquire
    pool.release = AsyncMock()
    return pool


@pytest.fixture(autouse=True)
def inject_pool(mock_pool):
    """Inject the mock pool into the database module for every test."""
    database.pool = mock_pool
    yield
    database.pool = None


# ── HMAC signature helper ─────────────────────────────────────────────────────


def make_signature(body: bytes, secret: str = "test-app-secret-32chars-padding000") -> str:
    """Return a valid X-Hub-Signature-256 header value for the given body."""
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


# ── FastAPI test client ───────────────────────────────────────────────────────


@pytest.fixture
async def client(mock_pool):
    """
    An httpx.AsyncClient wired to the FastAPI app.

    create_pool and close_pool are patched to no-ops so the lifespan runs
    without touching a real database. The mock pool is pre-injected via the
    inject_pool fixture (autouse=True), so all DB calls succeed.
    """
    from unittest.mock import patch

    from httpx import ASGITransport, AsyncClient

    from main import app

    with (
        patch("database.create_pool", new=AsyncMock()),
        patch("database.close_pool", new=AsyncMock()),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as c:
            yield c


# ── WhatsApp payload builder ──────────────────────────────────────────────────


def make_text_webhook_payload(phone: str, text: str, phone_number_id: str = "1234567890") -> bytes:
    """Build a minimal Meta webhook payload for a text message."""
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "metadata": {"phone_number_id": phone_number_id},
                            "messages": [
                                {
                                    "from": phone,
                                    "type": "text",
                                    "text": {"body": text},
                                }
                            ],
                        }
                    }
                ]
            }
        ]
    }
    return json.dumps(payload).encode()


def make_audio_webhook_payload(phone: str, media_id: str = "abc123") -> bytes:
    """Build a minimal Meta webhook payload for an audio message."""
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "metadata": {"phone_number_id": "1234567890"},
                            "messages": [
                                {
                                    "from": phone,
                                    "type": "audio",
                                    "audio": {"id": media_id, "mime_type": "audio/ogg"},
                                }
                            ],
                        }
                    }
                ]
            }
        ]
    }
    return json.dumps(payload).encode()
