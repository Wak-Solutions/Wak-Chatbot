"""agent.py — public entry point that orchestrates a full inbound→reply OpenAI turn."""

import logging
import re

import database
import memory
import menu as menu_nav
from config import OPENAI_MODEL
from intent import ai_scheduling_manually, wants_escalation, wants_meeting
from notifications import mask_phone, notify_dashboard
from prompt import detect_language

# Re-exports — kept at module top level so tests can patch via `agent.<name>`.
from _agent_utils import (
    client,
    normalise_menu_numbers,
    set_http_client,
)
from _agent_booking import _resolve_booking_url
from _agent_messages import build_messages
from _agent_openai import run_openai_turn, _OpenAITimeout

logger = logging.getLogger(__name__)


# Detects the global next-step menu the system prompt instructs the LLM to
# end every answer with. The exact pair is required (in either order of
# detection) so we don't mis-trigger on the company's own numbered menus.
# Arabic translations the LLM produces for the same labels are matched too.
_NEXT_STEP_OPTION_1_MARKERS = (
    "1. book a meeting",
    "1. حجز موعد",
    "1. حجز اجتماع",
)
_NEXT_STEP_OPTION_2_MARKERS = (
    "2. chat with an agent",
    "2. التحدث مع وكيل",
    "2. التحدث إلى وكيل",
    "2. الدردشة مع وكيل",
)


def _bot_just_offered_next_step_menu(history: list) -> bool:
    """Return True if the last assistant message ended with the global 1/2 menu."""
    for msg in reversed(history):
        if msg.get("role") == "assistant":
            content = (msg.get("content") or "").lower()
            has_1 = any(m in content for m in _NEXT_STEP_OPTION_1_MARKERS)
            has_2 = any(m in content for m in _NEXT_STEP_OPTION_2_MARKERS)
            return has_1 and has_2
    return False


def _reply_ends_with_next_step_menu(reply: str) -> bool:
    """Return True if the bot's reply contains the verbatim 1/2 menu."""
    if not reply:
        return False
    lower = reply.lower()
    has_1 = any(m in lower for m in _NEXT_STEP_OPTION_1_MARKERS)
    has_2 = any(m in lower for m in _NEXT_STEP_OPTION_2_MARKERS)
    return has_1 and has_2


def _is_next_step_choice(message: str) -> int | None:
    """Return 1, 2, or None — accepts Western and Arabic-Indic digits."""
    stripped = normalise_menu_numbers(message).strip()
    if stripped in ("1", "1.", "1)"):
        return 1
    if stripped in ("2", "2.", "2)"):
        return 2
    return None


async def get_reply(
    customer_phone: str,
    new_message: str,
    *,
    _save_inbound: bool = True,
    company_id: int = 1,
) -> tuple[str, str | None]:
    """Take a customer message, run the full OpenAI orchestration, return (reply, None)."""
    # ── Step 1: Load history ──────────────────────────────────────────────────
    history = await memory.load_history(customer_phone, company_id)

    # ── Step 2: Notify dashboard (fire-and-forget) ────────────────────────────
    await notify_dashboard(
        event="message",
        customer_phone=customer_phone,
        message_text=new_message,
        company_id=company_id,
    )

    # ── Step 2a: Deterministic next-step (1=meeting, 2=agent) router ─────────
    # The system prompt instructs the LLM to end every reply with a 1/2
    # "Book a meeting / Chat with an agent" menu. When the customer answers
    # with 1 or 2, route here instead of letting the company's menuConfig
    # navigator hijack the digit.
    _next_step_choice = _is_next_step_choice(new_message)
    if _next_step_choice is not None and _bot_just_offered_next_step_menu(history):
        if _save_inbound:
            await memory.save_message(
                customer_phone=customer_phone,
                direction="inbound",
                message_text=new_message,
                company_id=company_id,
            )
        if _next_step_choice == 1:
            pending_meeting = await database.get_pending_meeting(customer_phone, company_id)
            booking_url = await _resolve_booking_url(customer_phone, pending_meeting, company_id)
            if booking_url:
                logger.info(
                    "Next-step 1 → booking link sent — phone: %s",
                    mask_phone(customer_phone),
                )
                return (
                    f"Here's your personal booking link — valid for 24 hours: {booking_url}",
                    None,
                )
            # Booking URL unavailable — fall through to LLM so it can apologise.
        else:
            # Choice 2 → human handover; mirror the existing escalation path.
            logger.info(
                "Next-step 2 → human agent requested — phone: %s",
                mask_phone(customer_phone),
            )
            await notify_dashboard(
                event="human_requested",
                customer_phone=customer_phone,
                message_text=new_message,
                company_id=company_id,
            )
            handover_reply = "Connecting you to an agent now — please hold on a moment."
            return handover_reply, None

    # ── Step 2b: Deterministic menu navigation (company menuConfig) ───────────
    _conv_id = await memory.get_conversation_id(customer_phone, company_id)

    _menu_reply, _leaf_selection = await menu_nav.handle(
        customer_phone, company_id, new_message, _conv_id or ""
    )

    if _menu_reply is not None:
        if _save_inbound:
            await memory.save_message(
                customer_phone=customer_phone,
                direction="inbound",
                message_text=new_message,
                company_id=company_id,
            )
        logger.info(
            "Menu level sent — phone: %s",
            mask_phone(customer_phone),
        )
        return _menu_reply, None

    # ── Step 3: Human-agent request check ────────────────────────────────────
    if wants_escalation(new_message, history):
        logger.info(
            "Human agent requested — phone: %s",
            mask_phone(customer_phone),
        )
        await notify_dashboard(
            event="human_requested",
            customer_phone=customer_phone,
            message_text=new_message,
            company_id=company_id,
        )

    # ── Step 4: Meeting intent short-circuit ──────────────────────────────────
    pending_meeting = await database.get_pending_meeting(customer_phone, company_id)

    if wants_meeting(new_message, history):
        booking_url = await _resolve_booking_url(customer_phone, pending_meeting, company_id)
        if booking_url:
            booking_reply = (
                f"Here's your personal booking link — valid for 24 hours: {booking_url}"
            )
            if _save_inbound:
                await memory.save_message(
                    customer_phone=customer_phone,
                    direction="inbound",
                    message_text=new_message,
                    company_id=company_id,
                )
            logger.info(
                "Booking link sent — phone: %s",
                mask_phone(customer_phone),
            )
            return booking_reply, None

    # ── Step 5: Build message list ────────────────────────────────────────────
    messages = await build_messages(
        customer_phone=customer_phone,
        new_message=new_message,
        history=history,
        pending_meeting=pending_meeting,
        leaf_selection=_leaf_selection,
        company_id=company_id,
    )

    # ── Step 6+7: OpenAI call (with tool dispatch) ────────────────────────────
    logger.info(
        "OpenAI request — model: %s, history_len: %d, phone: %s",
        OPENAI_MODEL,
        len(history),
        mask_phone(customer_phone),
    )

    try:
        final_reply = await run_openai_turn(client, messages, customer_phone, company_id)
    except _OpenAITimeout as exc:
        return exc.fallback

    # ── Step 8: Safety nets ───────────────────────────────────────────────────

    # Replace [BOOKING_LINK] placeholder if OpenAI output it.
    if final_reply and (
        "[Booking Link]" in final_reply or "[BOOKING_LINK]" in final_reply
    ):
        logger.info(
            "Replacing [BOOKING_LINK] placeholder — phone: %s",
            mask_phone(customer_phone),
        )
        link_url = await _resolve_booking_url(customer_phone, pending_meeting, company_id)
        if link_url:
            final_reply = final_reply.replace("[Booking Link]", link_url).replace(
                "[BOOKING_LINK]", link_url
            )

    # Override if OpenAI tried to manually collect a date/time.
    if ai_scheduling_manually(final_reply):
        logger.info(
            "Overriding manual scheduling attempt — phone: %s",
            mask_phone(customer_phone),
        )
        override_url = await _resolve_booking_url(customer_phone, pending_meeting, company_id)
        if override_url:
            final_reply = (
                f"Here's your personal booking link — valid for 24 hours: {override_url}"
            )

    # ── Step 9: Save inbound only ─────────────────────────────────────────────
    if _save_inbound:
        await memory.save_message(
            customer_phone=customer_phone,
            direction="inbound",
            message_text=new_message,
            company_id=company_id,
        )

    # ── Step 10: (Re)initialise menu navigation for the next message ──────────
    # Skip the re-prime if the LLM ended with the global next-step menu —
    # otherwise the customer's "1" / "2" would be captured by the company
    # menuConfig navigator instead of the deterministic 1/2 router above.
    if (
        final_reply
        and not _reply_ends_with_next_step_menu(final_reply)
        and re.search(r"^\d+[\.\)]", final_reply, re.MULTILINE)
    ):
        _post_conv_id = await memory.get_conversation_id(customer_phone, company_id)
        if _post_conv_id:
            await menu_nav.start(customer_phone, company_id, _post_conv_id)

    if final_reply:
        final_reply = normalise_menu_numbers(final_reply)
    return final_reply, None
