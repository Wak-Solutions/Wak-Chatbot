"""
test_bugfixes.py — Regression tests for BUG-002 through BUG-009.

Each class is labelled with its bug ID so failures are immediately traceable.
"""

import json
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# BUG-003 — prompt.py tone resolution operator-precedence
# ---------------------------------------------------------------------------


class TestBug003ToneResolution:
    """raw_tone='Custom' + non-empty customTone → customTone, not 'professional'."""

    def test_custom_tone_with_value_returns_custom_tone(self):
        from prompt import build_system_prompt

        result = build_system_prompt(
            {"businessName": "Acme", "tone": "Custom", "customTone": "playful"}
        )
        assert "playful" in result
        assert "professional" not in result

    def test_custom_tone_with_empty_value_returns_professional(self):
        from prompt import build_system_prompt

        result = build_system_prompt(
            {"businessName": "Acme", "tone": "Custom", "customTone": ""}
        )
        assert "professional" in result

    def test_non_custom_tone_ignores_custom_tone_field(self):
        """raw_tone='Formal' must use 'formal', never the customTone value."""
        from prompt import build_system_prompt

        result = build_system_prompt(
            {"businessName": "Acme", "tone": "Formal", "customTone": "playful"}
        )
        assert "formal" in result
        assert "playful" not in result


# ---------------------------------------------------------------------------
# BUG-005 — lookup_order DB failure must not propagate out of agent.py
# ---------------------------------------------------------------------------


def _make_openai_response(content: str, tool_calls=None):
    msg = MagicMock()
    msg.content = content
    msg.tool_calls = tool_calls or []
    usage = MagicMock()
    usage.prompt_tokens = 10
    usage.completion_tokens = 5
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    resp.usage = usage
    return resp


def _make_tool_call(name: str, arguments: dict):
    tc = MagicMock()
    tc.id = "call_bug005"
    tc.function.name = name
    tc.function.arguments = json.dumps(arguments)
    return tc


class TestBug005LookupOrderError:
    """DB failure in lookup_order must not raise; tool message with error content must be appended."""

    async def test_db_failure_returns_error_tool_message(self, monkeypatch):
        mock_client = MagicMock()
        tool_call = _make_tool_call("lookup_order", {"order_number": "WAK-X"})
        first_resp = _make_openai_response(content=None, tool_calls=[tool_call])
        second_resp = _make_openai_response("Sorry, order lookup failed.")
        mock_client.chat.completions.create = AsyncMock(
            side_effect=[first_resp, second_resp]
        )
        monkeypatch.setattr("agent.client", mock_client)

        with (
            patch("memory.load_history", new=AsyncMock(return_value=[])),
            patch("memory.save_message", new=AsyncMock()),
            patch("notifications.notify_dashboard", new=AsyncMock()),
            patch("database.get_pending_meeting", new=AsyncMock(return_value=None)),
            patch("prompt.get_system_prompt", new=AsyncMock(return_value="System prompt")),
            patch(
                "database.lookup_order",
                new=AsyncMock(side_effect=RuntimeError("connection reset")),
            ),
            patch("memory.get_conversation_id", new=AsyncMock(return_value=None)),
        ):
            from agent import get_reply

            # Must not raise — the DB error is caught and converted to a tool result
            reply, _ = await get_reply("971501234567", "track WAK-X", company_id=1)

        # Second OpenAI call must have been made (tool result was appended)
        assert mock_client.chat.completions.create.call_count == 2

        # The tool message passed to the second call must contain the error payload
        second_call_messages = mock_client.chat.completions.create.call_args_list[1].kwargs[
            "messages"
        ]
        tool_messages = [m for m in second_call_messages if m.get("role") == "tool"]
        assert len(tool_messages) == 1
        content = json.loads(tool_messages[0]["content"])
        assert "error" in content
        assert "unavailable" in content["error"].lower()


# ---------------------------------------------------------------------------
# BUG-007 — malformed JSON webhook must return 200, not 403
# ---------------------------------------------------------------------------


class TestBug007MalformedJson:
    """POST /webhook with invalid JSON body → 200 so Meta stops retrying."""

    async def test_malformed_json_returns_200(self, client):
        resp = await client.post(
            "/webhook",
            content=b"not-valid-json{{{",
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": "sha256=deadbeef",
            },
        )
        assert resp.status_code == 200
        assert resp.json().get("status") == "ok"


# ---------------------------------------------------------------------------
# BUG-008 — intent.py word-boundary false positives
# ---------------------------------------------------------------------------


class TestBug008WordBoundaryFalsePositives:
    """Substring matches that should NOT trigger intent detection."""

    def test_management_does_not_trigger_agent_intent(self):
        from intent import wants_escalation

        assert not wants_escalation("I need help with management tasks")

    def test_agenda_does_not_trigger_agent_intent(self):
        from intent import wants_escalation

        assert not wants_escalation("Please send me the agenda")

    def test_facebook_does_not_trigger_booking_intent(self):
        from intent import wants_meeting

        assert not wants_meeting("I saw your ad on Facebook")

    def test_personally_does_not_trigger_human_intent(self):
        from intent import wants_escalation

        assert not wants_escalation("I personally love your product")

    def test_personalised_does_not_trigger_human_intent(self):
        from intent import wants_escalation

        assert not wants_escalation("I want a personalised experience")

    def test_slotful_does_not_trigger_meeting_intent(self):
        """'slot' inside another word must not fire."""
        from intent import wants_meeting

        # 'slothful' doesn't contain 'slot' but let's use a real compound
        assert not wants_meeting("There is no available timeslot right now")

    # Positive sanity checks — real keywords must still work after the change
    def test_agent_alone_triggers_escalation(self):
        from intent import wants_escalation

        assert wants_escalation("I want to talk to an agent")

    def test_book_alone_triggers_meeting(self):
        from intent import wants_meeting

        assert wants_meeting("I want to book a meeting")

    def test_person_alone_triggers_escalation(self):
        from intent import wants_escalation

        assert wants_escalation("Can I talk to a real person")


# ---------------------------------------------------------------------------
# BUG-009 — menu reset only when reply contains a numbered list
# ---------------------------------------------------------------------------


class TestBug009MenuResetHeuristic:
    """menu_nav.start() must only be called when the LLM reply has numbered options."""

    async def test_numbered_list_reply_resets_menu(self, monkeypatch):
        mock_client = MagicMock()
        numbered_reply = "How can I help?\n1. Track order\n2. Book meeting\n3. Speak to agent"
        mock_client.chat.completions.create = AsyncMock(
            return_value=_make_openai_response(numbered_reply)
        )
        monkeypatch.setattr("agent.client", mock_client)

        mock_menu_start = AsyncMock()
        with (
            patch("memory.load_history", new=AsyncMock(return_value=[])),
            patch("memory.save_message", new=AsyncMock()),
            patch("notifications.notify_dashboard", new=AsyncMock()),
            patch("database.get_pending_meeting", new=AsyncMock(return_value=None)),
            patch("prompt.get_system_prompt", new=AsyncMock(return_value="System")),
            patch("memory.get_conversation_id", new=AsyncMock(return_value="conv-abc")),
            patch("menu.start", mock_menu_start),
        ):
            from agent import get_reply

            await get_reply("971501234567", "hello", company_id=1)

        mock_menu_start.assert_called_once()

    async def test_plain_reply_does_not_reset_menu(self, monkeypatch):
        mock_client = MagicMock()
        plain_reply = "Thank you for reaching out! How can I help you today?"
        mock_client.chat.completions.create = AsyncMock(
            return_value=_make_openai_response(plain_reply)
        )
        monkeypatch.setattr("agent.client", mock_client)

        mock_menu_start = AsyncMock()
        with (
            patch("memory.load_history", new=AsyncMock(return_value=[])),
            patch("memory.save_message", new=AsyncMock()),
            patch("notifications.notify_dashboard", new=AsyncMock()),
            patch("database.get_pending_meeting", new=AsyncMock(return_value=None)),
            patch("prompt.get_system_prompt", new=AsyncMock(return_value="System")),
            patch("memory.get_conversation_id", new=AsyncMock(return_value="conv-abc")),
            patch("menu.start", mock_menu_start),
        ):
            from agent import get_reply

            await get_reply("971501234567", "hello", company_id=1)

        mock_menu_start.assert_not_called()


# ---------------------------------------------------------------------------
# BUG-002 — _resolve_booking_url advisory lock prevents duplicate tokens
# ---------------------------------------------------------------------------


class TestBug002AdvisoryLock:
    """When advisory lock is not acquired, existing token is returned instead of creating new one."""

    def _make_conn(self, fetchval_return, fetchrow_return=None):
        """Build a mock asyncpg connection where transaction() is a proper async CM."""
        conn = MagicMock()
        # transaction() must be a sync call returning an async context manager object
        txn = MagicMock()
        txn.__aenter__ = AsyncMock(return_value=None)
        txn.__aexit__ = AsyncMock(return_value=False)
        conn.transaction = MagicMock(return_value=txn)
        conn.fetchval = AsyncMock(return_value=fetchval_return)
        conn.fetchrow = AsyncMock(return_value=fetchrow_return)
        return conn

    async def test_lock_not_acquired_returns_existing_token(self):
        """pg_try_advisory_xact_lock returns False → reuse existing token, don't POST."""
        mock_conn = self._make_conn(
            fetchval_return=False,
            fetchrow_return={"meeting_token": "existing-token-abc"},
        )
        mock_pool = MagicMock()
        mock_pool.acquire = AsyncMock(return_value=mock_conn)
        mock_pool.release = AsyncMock()

        with patch("database.pool", mock_pool):
            from agent import _resolve_booking_url

            result = await _resolve_booking_url("971501234567", None, company_id=1)

        assert result is not None
        assert "existing-token-abc" in result
        # fetchval called once for the lock; no HTTP create-token call
        mock_conn.fetchval.assert_called_once()

    async def test_lock_acquired_no_existing_token_creates_new(self):
        """Lock acquired, no existing token → POST to create-token."""
        import httpx
        import agent

        mock_conn = self._make_conn(fetchval_return=True, fetchrow_return=None)
        mock_pool = MagicMock()
        mock_pool.acquire = AsyncMock(return_value=mock_conn)
        mock_pool.release = AsyncMock()

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"token": "new-token-xyz"}

        mock_http = MagicMock(spec=httpx.AsyncClient)
        mock_http.post = AsyncMock(return_value=mock_resp)
        mock_http.aclose = AsyncMock()

        agent.set_http_client(mock_http)
        try:
            with (
                patch("database.pool", mock_pool),
                patch(
                    "database.get_webhook_secret_by_company_id",
                    new=AsyncMock(return_value="secret"),
                ),
            ):
                from agent import _resolve_booking_url

                result = await _resolve_booking_url("971501234567", None, company_id=1)
        finally:
            agent.set_http_client(None)  # type: ignore[arg-type]

        assert result is not None
        assert "new-token-xyz" in result


# ---------------------------------------------------------------------------
# BUG-004 — memory.save_message advisory lock prevents split conversation_id
# ---------------------------------------------------------------------------


class TestBug004ConversationIdLock:
    """Advisory lock is acquired before resolving conversation_id."""

    def _patch_transaction(self, mock_conn):
        """Fix mock_conn.transaction to be a sync call returning an async CM.

        conftest creates transaction as AsyncMock (returns coroutine on call),
        but asyncpg's conn.transaction() is synchronous — it returns an object
        that is itself an async context manager. Override for memory.py tests.
        """
        txn = MagicMock()
        txn.__aenter__ = AsyncMock(return_value=None)
        txn.__aexit__ = AsyncMock(return_value=False)
        mock_conn.transaction = MagicMock(return_value=txn)

    async def test_advisory_lock_called_before_select(self, mock_conn):
        """pg_advisory_xact_lock must be called inside the transaction before SELECT."""
        self._patch_transaction(mock_conn)
        call_order = []

        async def track_fetchval(sql, *args):
            call_order.append(("fetchval", sql))
            return None

        async def track_fetchrow(sql, *args):
            call_order.append(("fetchrow", sql))
            return None

        mock_conn.fetchval = track_fetchval
        mock_conn.fetchrow = track_fetchrow

        with patch("database.auto_capture_contact", new=AsyncMock()):
            import memory

            await memory.save_message(
                customer_phone="971500000000",
                direction="inbound",
                message_text="Hello",
                company_id=1,
            )

        assert len(call_order) >= 2
        first_op, first_sql = call_order[0]
        assert first_op == "fetchval"
        assert "pg_advisory_xact_lock" in first_sql

        second_op, second_sql = call_order[1]
        assert second_op == "fetchrow"
        assert "conversation_id" in second_sql

    async def test_existing_conversation_id_reused(self, mock_conn):
        """When a recent message exists, its conversation_id is reused."""
        import uuid

        self._patch_transaction(mock_conn)
        existing_id = str(uuid.uuid4())

        async def fetchval_lock(sql, *args):
            return None

        async def fetchrow_conv(sql, *args):
            return {"conversation_id": existing_id}

        mock_conn.fetchval = fetchval_lock
        mock_conn.fetchrow = fetchrow_conv

        with patch("database.auto_capture_contact", new=AsyncMock()):
            import memory

            await memory.save_message(
                customer_phone="971500000000",
                direction="inbound",
                message_text="Second message",
                company_id=1,
            )

        insert_call = mock_conn.execute.call_args
        assert existing_id in insert_call.args
