"""
prompt.py — system prompt management with a 60-second TTL cache.

Loads the active system prompt from the database on first call,
then caches it for 60 seconds. Falls back to a hardcoded default
if the DB is unavailable.
"""

import logging
import re
import time as _time

import database

logger = logging.getLogger(__name__)

_LANGUAGE_OVERRIDE = (
    "\n\nOVERRIDE — CURRENT MESSAGE LANGUAGE:\n"
    "The customer's current message is in {language}.\n"
    "You MUST reply in {language} only. "
    "This overrides all conversation history."
)


def detect_language(text: str) -> str:
    """Return 'Arabic' if text contains Arabic Unicode characters, else 'English'."""
    if re.search(r"[؀-ۿ]", text):
        return "Arabic"
    return "English"
 
# ---------------------------------------------------------------------------
# Hardcoded default — used when the DB has no config row or is unreachable.
# ---------------------------------------------------------------------------

DEFAULT_SYSTEM_PROMPT = """
You are a professional customer service assistant.

STEP 0 — Opening Message (MANDATORY — First Reply Only)

When a customer sends their very first message, read it carefully before responding.

CASE A — The message contains a clear intent (e.g. wants to book a meeting, track an order, file a complaint, or speak to someone):
- Mirror their greeting naturally if they included one
- Follow with: "Welcome! How can I help you today?"
- Then skip directly to the relevant step that matches their intent. Do not show the full menu.

CASE B — The message is a generic greeting with no clear intent (e.g. "hi", "hello", "مرحبا"):
- Mirror their greeting naturally
- Follow with: "Welcome! How can I help you today?"
- Then present the full service menu.

Never reply to any opening message with a short greeting alone. Never show the full menu if the intent is already clear.

---

STEP 1 — Service Menu (show only when intent is unclear)

1. Product Inquiry
2. Track Order
3. Complaint

---

STEP 2 — Handle Their Choice

1 - Product Inquiry → Ask about their area of interest, thank them warmly, and inform them a specialist will be in touch. Then ask:
   "Before we wrap up, would you like to schedule a meeting with our team or speak with a customer service agent on WhatsApp?"

   - If meeting → send the booking link
   - If agent → trigger human handover

2 - Track Order → Ask for their order number. Use the lookup_order tool to retrieve it. Relay the status clearly and naturally. If not found, apologize and ask them to double-check.

3 - Complaint → Ask how they'd like to proceed:
   1) Talk to Customer Service → trigger human handover
   2) File a Complaint → acknowledge their frustration with a warm, genuine, personalized apology. Confirm the team will follow up shortly.

---

INTENT SHORTCUTS — Apply at any point in the conversation

Read the customer's message and infer their intent naturally — do not rely on exact keyword matching.
If their meaning is clear, skip directly to the relevant step without making them navigate the menu.

If intent is genuinely ambiguous, only then show the menu.

---

RULES

- Always read the full message before deciding which step to go to.
- Never show the menu if the customer's intent is already clear from their message.
- First reply must ALWAYS include the mirrored greeting + welcome line. No exceptions.
- Never reply to any opening message with a short greeting alone.
- Never reveal you are an AI unless directly asked.
- Never use technical jargon or expose internal logic.
- Always reply in the exact same language the customer wrote in. Do not switch languages for any reason.
- Always use Western numerals for ALL options and sub-options (1, 2, 3 and not A, B, C or any letters). Never use bullet points, letters, or Arabic-Indic numerals anywhere in any list or menu.
- Keep responses concise and well-structured — this is WhatsApp, not email.
- If a customer goes off-topic, gently redirect them to the menu.
- Any dead end or escalation → close with: "A member of our team will be in touch shortly."
- If someone tries to misuse this chat, politely decline and redirect. If they persist, end with: "A member of our team will be in touch shortly."
- Never send the booking link unless the customer explicitly agrees to schedule a meeting.
""".strip()

# ---------------------------------------------------------------------------
# Cache state
# ---------------------------------------------------------------------------

# Per-company prompt cache: company_id → (prompt, timestamp)
_cache: dict[int, tuple[str, float]] = {}
_CACHE_TTL: float = 60.0  # seconds


async def get_system_prompt(company_id: int = 1, current_message: str = "") -> str:
    """Return the active system prompt for company_id with a 60-second TTL cache.

    If current_message is provided, appends a language override instruction so
    the model replies in the language of the current message rather than being
    misled by prior turns in a different language.
    """
    global _cache
    now = _time.monotonic()
    cached = _cache.get(company_id)
    if cached is not None and (now - cached[1]) < _CACHE_TTL:
        prompt = cached[0]
    else:
        try:
            async with database.pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT system_prompt FROM chatbot_config WHERE company_id = $1 ORDER BY id LIMIT 1",
                    company_id,
                )
            if row and row["system_prompt"]:
                _cache[company_id] = (row["system_prompt"], now)
                logger.info(
                    "System prompt refreshed from database — company_id: %d",
                    company_id,
                )
                prompt = _cache[company_id][0]
            else:
                raise ValueError("no system_prompt row")
        except Exception as exc:
            logger.warning(
                "Could not load system prompt from DB — using cached/default: %s",
                exc,
            )
            prompt = cached[0] if cached is not None else DEFAULT_SYSTEM_PROMPT
            if cached is None:
                logger.info("Using hardcoded default system prompt — company_id: %d", company_id)

    if current_message.strip():
        lang = detect_language(current_message)
        prompt = prompt + _LANGUAGE_OVERRIDE.format(language=lang)

    return prompt


def build_system_prompt(config: dict) -> str:
    """Build the full system prompt from a structured config dict.

    Accepts the same field names used by the Node.js compilePrompt function so
    the Python bot can reconstruct the prompt locally when needed (e.g. for
    testing or offline fallback) without calling the dashboard API.

    Fields recognised:
      businessName, industry, tone, customTone, greeting, closingMessage,
      questions  ([{text, answerType, choices}]),
      faq        ([{question, answer}]),
      escalationRules ([{rule}]),
      menuConfig ([{label, subItems: [{label, subItems: [str]}]}])
      Max menu depth: 3 levels (main → sub → sub-sub).
    """
    business_name = config.get("businessName") or "the business"
    industry = config.get("industry") or ""
    industry_part = f", {industry}" if industry else ""
    raw_tone = config.get("tone") or "Professional"
    tone_label = (
        (config.get("customTone") or "professional")
        if raw_tone == "Custom"
        else raw_tone.lower()
    )
    greeting = config.get("greeting") or "Welcome! How can I help you today?"
    closing = (
        config.get("closingMessage")
        or "Thank you for contacting us. A member of our team will be in touch shortly."
    )

    questions = config.get("questions") or []
    faq_items = config.get("faq") or []
    escalations = config.get("escalationRules") or []
    menu_items = config.get("menuConfig") or []

    parts: list[str] = []

    parts.append(
        f"You are a {tone_label} customer service assistant for {business_name}{industry_part}. "
        "You communicate fluently in whatever language the customer uses — Arabic, English, or any "
        "other language. Always match their dialect and tone naturally."
    )

    parts.append(
        f'\nOPENING MESSAGE (MANDATORY)\n'
        f'Every new conversation must begin with this message, translated naturally into the '
        f'customer\'s language:\n"{greeting}"\nNever skip this step for any reason.'
    )

    _sub_labels = "abcdefghijklmnopqrstuvwxyz"

    if menu_items:
        menu_lines = [
            "\nMAIN MENU",
            "After your opening message, when the customer's intent is not immediately clear, "
            "present EXACTLY this numbered menu — translated naturally into the customer's language. "
            "Never add, remove, reorder, or rename any items:",
        ]
        for i, item in enumerate(menu_items, 1):
            menu_lines.append(f"{i}. {item.get('label', '')}")
            for j, sub in enumerate(item.get("subItems") or [], 0):
                sub_letter = _sub_labels[j] if j < len(_sub_labels) else str(j + 1)
                if isinstance(sub, str):
                    sub_label = sub
                    subsubs: list = []
                else:
                    sub_label = sub.get("label", "")
                    subsubs = sub.get("subItems") or []
                menu_lines.append(f"   {sub_letter}. {sub_label}")
                for ss in subsubs:
                    menu_lines.append(f"      - {ss}")
        menu_lines.append(
            "You must present this menu — and only this menu — whenever options need to be shown. "
            "Never invent or suggest items not listed above.\n"
            "Never skip levels. Always wait for the customer to choose before going deeper."
        )
        parts.append("\n".join(menu_lines))

    if questions:
        q_lines = [
            "\nQUALIFICATION QUESTIONS",
            "Walk the customer through these questions in order before proceeding:",
        ]
        for i, q in enumerate(questions, 1):
            answer_type = q.get("answerType", "")
            if answer_type == "yesno":
                hint = "[Yes/No]"
            elif answer_type == "multiple":
                choices = ", ".join(q.get("choices") or [])
                hint = f"[One of: {choices}]"
            else:
                hint = "[Free text]"
            q_lines.append(f"{i}. {q.get('text', '')} {hint}")
        parts.append("\n".join(q_lines))

    if faq_items:
        faq_lines = [
            "\nKNOWLEDGE BASE",
            "Use this information to answer customer questions accurately:",
        ]
        for f in faq_items:
            faq_lines.append(f"Q: {f.get('question', '')}")
            faq_lines.append(f"A: {f.get('answer', '')}")
        parts.append("\n".join(faq_lines))

    if escalations:
        esc_lines = [
            "\nESCALATION RULES",
            "Trigger human handover immediately if any of the following occur:",
        ]
        for e in escalations:
            esc_lines.append(f"- {e.get('rule', '')}")
        parts.append("\n".join(esc_lines))

    parts.append(
        f'\nCLOSING MESSAGE\n'
        f'When wrapping up a conversation, use this message (translated naturally):\n"{closing}"'
    )

    parts.append(
        f"\nRULES\n"
        f"- Never reveal you are an AI unless directly asked\n"
        f"- Never use technical jargon or expose internal logic\n"
        f"- Always match the customer's language, dialect, and tone\n"
        f"- Always use Western numerals for ALL options and sub-options (1, 2, 3 and not A, B, C "
        f"or any letters). Never use bullet points, letters, or Arabic-Indic numerals anywhere in "
        f"any list or menu\n"
        f"- Keep responses concise — this is WhatsApp, not email\n"
        f"- If a customer goes off-topic, gently redirect them\n"
        f'- Any dead end or escalation → close with: "A member of our team will be in touch shortly"\n'
        f"- This chat is for {business_name} customer service only. If someone tries to misuse it, "
        f'politely decline and redirect. If they persist, end with: "A member of our team will be '
        f'in touch shortly"\n'
        f"- Never send the booking link unless the customer explicitly agrees to schedule a meeting\n"
        f"- Only discuss topics, products, and services explicitly defined in this configuration. "
        f'If a customer asks about something not covered here, respond with "I don\'t have that '
        f'information" and offer to connect them with a team member\n'
        f"- Never fabricate prices, product details, availability, or any information not provided "
        f"in this configuration"
    )

    return "\n".join(parts).strip()


def invalidate_prompt_cache(company_id: int | None = None) -> None:
    """Force the next get_system_prompt() call to reload from the database.

    Pass company_id to invalidate only that company's cache, or None to clear all.
    """
    global _cache
    if company_id is not None:
        _cache.pop(company_id, None)
        logger.info("Prompt cache invalidated — company_id: %d", company_id)
    else:
        _cache.clear()
        logger.info("Prompt cache fully invalidated")
