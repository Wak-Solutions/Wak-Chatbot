"""
test_memory.py — Tests for memory.py (load_history and save_message).
"""

from unittest.mock import AsyncMock, patch

import pytest

import database
import memory


@pytest.fixture(autouse=True)
def reset_known_contacts():
    """Clear the in-process contact cache so each test starts fresh."""
    memory._known_contacts.clear()
    yield
    memory._known_contacts.clear()


class TestLoadHistory:
    async def test_returns_empty_list_for_new_customer(self, mock_conn):
        mock_conn.fetch.return_value = []
        history = await memory.load_history("971500000000", company_id=1)
        assert history == []

    async def test_maps_customer_sender_to_user_role(self, mock_conn):
        mock_conn.fetch.return_value = [
            {"role": "customer", "message_text": "Hello"},
        ]
        history = await memory.load_history("971500000000", company_id=1)
        assert history[0]["role"] == "user"
        assert history[0]["content"] == "Hello"

    async def test_maps_ai_sender_to_assistant_role(self, mock_conn):
        mock_conn.fetch.return_value = [
            {"role": "ai", "message_text": "How can I help?"},
        ]
        history = await memory.load_history("971500000000", company_id=1)
        assert history[0]["role"] == "assistant"

    async def test_history_returned_in_order(self, mock_conn):
        """load_history should return messages oldest-first (DB sub-query re-orders them)."""
        mock_conn.fetch.return_value = [
            {"role": "customer", "message_text": "First"},
            {"role": "ai", "message_text": "Second"},
            {"role": "customer", "message_text": "Third"},
        ]
        history = await memory.load_history("971500000000", company_id=1)
        assert [m["content"] for m in history] == ["First", "Second", "Third"]

    async def test_respects_company_id_parameter(self, mock_conn):
        """The company_id must be passed as the third parameter to conn.fetch."""
        mock_conn.fetch.return_value = []
        await memory.load_history("971500000000", company_id=42)
        call_args = mock_conn.fetch.call_args
        # Third positional arg ($3 in SQL) should be company_id=42
        assert 42 in call_args.args

    async def test_raises_on_db_error(self, mock_pool, mock_conn):
        """load_history should re-raise DB exceptions (not silently swallow them)."""
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def broken_acquire():
            raise RuntimeError("DB error")
            yield

        mock_pool.acquire = broken_acquire
        database.pool = mock_pool

        with pytest.raises(RuntimeError, match="DB error"):
            await memory.load_history("971500000000", company_id=1)


class TestSaveMessage:
    async def test_saves_inbound_message(self, mock_conn):
        with patch("database.auto_capture_contact", new=AsyncMock()):
            await memory.save_message(
                customer_phone="971500000000",
                direction="inbound",
                message_text="Hello",
                company_id=1,
            )
        mock_conn.execute.assert_called_once()
        sql = mock_conn.execute.call_args.args[0]
        assert "INSERT INTO messages" in sql

    async def test_defaults_sender_to_customer_for_inbound(self, mock_conn):
        with patch("database.auto_capture_contact", new=AsyncMock()):
            await memory.save_message(
                customer_phone="971500000000",
                direction="inbound",
                message_text="Hi",
                company_id=1,
            )
        args = mock_conn.execute.call_args.args
        # sender is the 3rd parameter ($3) — should be "customer"
        assert "customer" in args

    async def test_defaults_sender_to_ai_for_outbound(self, mock_conn):
        await memory.save_message(
            customer_phone="971500000000",
            direction="outbound",
            message_text="Hello!",
            company_id=1,
        )
        args = mock_conn.execute.call_args.args
        assert "ai" in args

    async def test_explicit_sender_override(self, mock_conn):
        await memory.save_message(
            customer_phone="971500000000",
            direction="outbound",
            message_text="Hello from agent",
            sender="agent",
            company_id=1,
        )
        args = mock_conn.execute.call_args.args
        assert "agent" in args

    async def test_inbound_triggers_auto_capture_contact(self, mock_conn):
        """Inbound messages should trigger auto_capture_contact."""
        with patch("database.auto_capture_contact", new=AsyncMock()) as mock_capture:
            await memory.save_message(
                customer_phone="971500000000",
                direction="inbound",
                message_text="Hi",
                company_id=1,
            )
        mock_capture.assert_called_once_with("971500000000", 1)

    async def test_outbound_does_not_trigger_auto_capture(self, mock_conn):
        """Outbound messages should NOT trigger auto_capture_contact."""
        with patch("database.auto_capture_contact", new=AsyncMock()) as mock_capture:
            await memory.save_message(
                customer_phone="971500000000",
                direction="outbound",
                message_text="Reply",
                company_id=1,
            )
        mock_capture.assert_not_called()
