"""
test_agent.py — Tests for agent.py (OpenAI orchestration).

All external calls (OpenAI, database, WhatsApp, notifications) are mocked.
Tests verify the routing logic, not the AI model output.
"""

import json
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_openai_response(content: str, tool_calls=None):
    """Build a mock openai.ChatCompletion response object."""
    msg = MagicMock()
    msg.content = content
    msg.tool_calls = tool_calls or []

    usage = MagicMock()
    usage.prompt_tokens = 100
    usage.completion_tokens = 50

    choice = MagicMock()
    choice.message = msg

    resp = MagicMock()
    resp.choices = [choice]
    resp.usage = usage
    return resp


def _make_tool_call(name: str, arguments: dict):
    tc = MagicMock()
    tc.id = "call_123"
    tc.function.name = name
    tc.function.arguments = json.dumps(arguments)
    return tc


@pytest.fixture
def mock_openai(monkeypatch):
    """Patch agent.client (the AsyncOpenAI instance) with a mock."""
    mock_client = MagicMock()
    mock_client.chat = MagicMock()
    mock_client.chat.completions = MagicMock()
    mock_client.chat.completions.create = AsyncMock(
        return_value=_make_openai_response("Hello! How can I help?")
    )
    monkeypatch.setattr("agent.client", mock_client)
    return mock_client


@pytest.fixture
def mock_externals():
    """Patch all I/O outside of the OpenAI call."""
    with (
        patch("memory.load_history", new=AsyncMock(return_value=[])),
        patch("memory.save_message", new=AsyncMock()),
        patch("notifications.notify_dashboard", new=AsyncMock()),
        patch("database.get_pending_meeting", new=AsyncMock(return_value=None)),
        patch("prompt.get_system_prompt", new=AsyncMock(return_value="System prompt")),
    ):
        yield


class TestGetReply:
    async def test_returns_ai_reply(self, mock_openai, mock_externals):
        """get_reply returns the text from OpenAI."""
        from agent import get_reply

        reply, meeting_msg = await get_reply(
            customer_phone="971501234567",
            new_message="Hello",
            company_id=1,
        )
        assert reply == "Hello! How can I help?"
        assert meeting_msg is None

    async def test_saves_inbound_message(self, mock_openai, mock_externals):
        """Inbound message must be written to memory by agent.get_reply.

        Outbound persistence moved to main.py (after whatsapp.send_message
        succeeds), so a Meta send failure doesn't leave a ghost reply in
        the dashboard. agent.get_reply only saves the inbound side.
        """
        from agent import get_reply

        with patch("memory.save_message", new=AsyncMock()) as mock_save:
            await get_reply("971501234567", "Hi", company_id=1)

        calls = mock_save.call_args_list
        directions = [c.kwargs.get("direction") or c.args[1] for c in calls]
        assert "inbound" in directions

    async def test_skip_inbound_save_when_flag_false(self, mock_openai, mock_externals):
        """With _save_inbound=False, agent.get_reply saves nothing.

        Outbound is persisted by main.py after the WhatsApp send succeeds,
        not by agent.py — so when the inbound flag is off there should be
        no save_message calls from this code path at all.
        """
        from agent import get_reply

        with patch("memory.save_message", new=AsyncMock()) as mock_save:
            await get_reply("971501234567", "Hi", _save_inbound=False, company_id=1)

        calls = mock_save.call_args_list
        directions = [c.kwargs.get("direction") or c.args[1] for c in calls]
        assert "inbound" not in directions

    async def test_meeting_intent_short_circuits_openai(self, mock_openai, mock_externals):
        """When the message contains a meeting keyword, OpenAI is never called."""
        from agent import get_reply

        with (
            patch("memory.load_history", new=AsyncMock(return_value=[])),
            patch("database.get_pending_meeting", new=AsyncMock(return_value=None)),
            patch("agent._resolve_booking_url", new=AsyncMock(return_value="http://localhost:5000/book/token-abc")),
            patch("memory.save_message", new=AsyncMock()),
            patch("notifications.notify_dashboard", new=AsyncMock()),
        ):
            reply, _ = await get_reply("971501234567", "I want to book a meeting", company_id=1)

        mock_openai.chat.completions.create.assert_not_called()
        assert "http://localhost:5000/book/token-abc" in reply

    async def test_tool_call_lookup_order(self, mock_openai, mock_externals):
        """When OpenAI returns a lookup_order tool call, it is executed and a second call is made."""
        from agent import get_reply

        tool_call = _make_tool_call("lookup_order", {"order_number": "WAK-001"})
        first_resp = _make_openai_response(content=None, tool_calls=[tool_call])
        second_resp = _make_openai_response("Your order WAK-001 is shipped.")
        mock_openai.chat.completions.create = AsyncMock(
            side_effect=[first_resp, second_resp]
        )

        with patch(
            "database.lookup_order",
            new=AsyncMock(return_value={"found": True, "status": "shipped"}),
        ):
            reply, _ = await get_reply("971501234567", "track WAK-001", company_id=1)

        assert mock_openai.chat.completions.create.call_count == 2
        assert reply == "Your order WAK-001 is shipped."

    async def test_tool_call_order_not_found(self, mock_openai, mock_externals):
        """lookup_order returning found=False results in a second OpenAI call with that result."""
        from agent import get_reply

        tool_call = _make_tool_call("lookup_order", {"order_number": "INVALID"})
        first_resp = _make_openai_response(content=None, tool_calls=[tool_call])
        second_resp = _make_openai_response("Sorry, no order found.")
        mock_openai.chat.completions.create = AsyncMock(side_effect=[first_resp, second_resp])

        with patch(
            "database.lookup_order",
            new=AsyncMock(return_value={"found": False, "message": "No order found"}),
        ):
            reply, _ = await get_reply("971501234567", "track INVALID", company_id=1)

        assert reply == "Sorry, no order found."

    async def test_escalation_intent_triggers_notify_dashboard(self, mock_openai, mock_externals):
        """A message containing 'agent' should trigger an escalation notification."""
        from agent import get_reply

        # agent.py uses `from notifications import notify_dashboard`, so the bound
        # reference lives on the agent module — patch it there, not on notifications.
        with patch("agent.notify_dashboard", new=AsyncMock()) as mock_notify:
            await get_reply("971501234567", "I want to speak to an agent", company_id=1)

        # agent.py emits event="human_requested" for human-agent escalation intent.
        escalation_calls = [
            c for c in mock_notify.call_args_list
            if c.kwargs.get("event") == "human_requested" or (c.args and c.args[0] == "human_requested")
        ]
        assert len(escalation_calls) >= 1

    async def test_ai_scheduling_override(self, mock_openai, mock_externals):
        """If OpenAI tries to collect a date/time, the reply is replaced with the booking link."""
        from agent import get_reply

        mock_openai.chat.completions.create = AsyncMock(
            return_value=_make_openai_response("What date would you prefer?")
        )

        with patch(
            "agent._resolve_booking_url",
            new=AsyncMock(return_value="http://localhost:5000/book/xyz"),
        ):
            reply, _ = await get_reply("971501234567", "I want a meeting", company_id=1)

        assert "http://localhost:5000/book/xyz" in reply
        assert "What date" not in reply
