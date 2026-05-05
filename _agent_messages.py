"""_agent_messages.py — build OpenAI message list (system prompt + history + final language enforcement)."""

import menu as menu_nav
from config import DASHBOARD_URL
from prompt import detect_language, get_system_prompt


async def build_messages(
    customer_phone: str,
    new_message: str,
    history: list,
    pending_meeting: dict | None,
    leaf_selection: str | None,
    company_id: int,
) -> list:
    """Construct the OpenAI messages list with system prompt, history, user message, and language enforcement."""
    system_content = await get_system_prompt(company_id, current_message=new_message)

    # Append a menu-navigation override so OpenAI only ever shows the top-level
    # items — sub-levels are handled deterministically by menu_nav.handle().
    _top_menu = await menu_nav.format_top_level(company_id)
    if _top_menu:
        system_content += (
            "\n\nMENU NAVIGATION RULE (overrides the MAIN MENU section above):\n"
            "When presenting the service menu, display ONLY the top-level options "
            "listed below — NEVER show sub-items. The customer selects by number and "
            "the sub-options are delivered automatically.\n"
            + _top_menu
            + "\nWait for the customer to reply with a number before going deeper."
        )

    # Inject a real booking URL into the system prompt so OpenAI never
    # invents a fake one. If no pending token exists, instruct OpenAI to
    # output a known placeholder that we catch and replace below.
    _injected_booking_url = None
    if pending_meeting and pending_meeting.get("scheduled_at") is None:
        _t = pending_meeting.get("meeting_token")
        if _t:
            _injected_booking_url = f"{DASHBOARD_URL}/book/{_t}"

    if _injected_booking_url:
        system_content += (
            f"\n\nBOOKING URL: {_injected_booking_url}\n"
            "When sending the customer a meeting/booking link, use this exact URL. "
            "Do NOT invent, shorten, or modify it."
        )
    else:
        system_content += (
            "\n\nWhen sending the customer a meeting/booking link, output the literal "
            "text [BOOKING_LINK] as a placeholder — it will be replaced automatically. "
            "Do NOT invent a URL."
        )

    # When the customer just reached a leaf node in the menu tree, replace the
    # bare number they sent with a meaningful description so OpenAI can respond
    # correctly without seeing the full navigation history.
    _effective_message = (
        f"I'd like to enquire about: {leaf_selection}"
        if leaf_selection
        else new_message
    )

    _lang = detect_language(new_message)
    messages = (
        [{"role": "system", "content": system_content}]
        + history
        + [{"role": "user", "content": _effective_message}]
        + [{"role": "system", "content": (
            f"FINAL INSTRUCTION: The customer just wrote in {_lang}. "
            f"Your response MUST be in {_lang} only. "
            f"Do not use any other language under any circumstances."
        )}]
    )
    return messages
