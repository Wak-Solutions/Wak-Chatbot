"""
intent.py — pure intent detection for the WhatsApp bot.

All functions here are stateless and have zero side effects.
They can be unit-tested without importing OpenAI, database, or httpx.
"""

import re

# ---------------------------------------------------------------------------
# Matching helpers
# ---------------------------------------------------------------------------


def _kw_match(keyword: str, text: str) -> bool:
    """
    Return True if keyword appears in text.

    Single-word ASCII keywords use word-boundary regex to avoid substring
    false positives ("book" in "Facebook", "agent" in "management").
    Multi-word phrases and non-ASCII (Arabic) use plain substring matching
    because \b is unreliable for Unicode and phrase boundaries are explicit.
    """
    if " " in keyword or not keyword.isascii():
        return keyword in text
    return bool(re.search(r"\b" + re.escape(keyword) + r"\b", text))


# ---------------------------------------------------------------------------
# Keyword sets
# ---------------------------------------------------------------------------

# Phrases that signal the bot has closed a conversation topic and a
# meeting offer should be sent to the customer.
_RESOLUTION_PHRASES = [
    "specialist will be in touch",
    "a member of our team will",
    "the team will follow up",
    "will be in touch shortly",
]

_MEETING_KEYWORDS = [
    "meeting", "book", "schedule", "appointment", "slot",
    # affirmatives — only matched when the bot just asked the meeting/agent question
    "yes", "yeah", "sure", "ok", "okay", "yep", "please", "definitely", "great",
    # Arabic affirmatives and meeting words
    "نعم", "اوكي", "تمام", "حسنا", "ايوه", "اه", "موافق", "اجتماع", "موعد", "حجز",
]

# Phrases that indicate the last bot message was the meeting-or-agent question.
_MEETING_QUESTION_PHRASES = [
    "schedule a meeting", "book a meeting", "meeting with our team",
    "speak with a customer service agent", "whatsapp agent",
    "اجتماع", "موعد", "واتساب",
]

# Keywords that indicate the customer wants to speak to a human agent.
_ESCALATION_KEYWORDS = [
    "agent", "human", "person", "staff", "representative", "support",
    "customer service", "talk to someone", "speak to someone", "real person",
    "live agent", "live person", "call me", "phone call",
    # Arabic
    "وكيل", "انسان", "موظف", "خدمة العملاء", "دعم", "شخص حقيقي",
    "تحدث مع شخص", "اريد شخص", "أريد شخص",
]

# Phrases that indicate the last bot message explicitly offered the agent option.
_AGENT_OFFER_PHRASES = [
    "speak with a customer service agent",
    "whatsapp agent",
    "customer service agent on whatsapp",
    "تحدث مع وكيل",
    "خدمة العملاء على واتساب",
]

# Phrases that mean the AI is wrongly trying to collect a date/time manually.
_AI_SCHEDULING_PHRASES = [
    "what date", "what time", "when would you like", "preferred time",
    "preferred date", "which day", "choose a date", "pick a time",
    "let me know when", "what day works", "suggest a time",
    "أي يوم", "متى تريد", "اختر موعد", "حدد وقت",
]

# Ambiguous affirmatives — only count as meeting/escalation intent with context.
_AMBIGUOUS_AFFIRMATIVES = {
    "yes", "yeah", "sure", "ok", "okay", "yep", "please",
    "definitely", "great", "نعم", "اوكي", "تمام", "حسنا",
    "ايوه", "اه", "موافق",
}

# ---------------------------------------------------------------------------
# Detection functions
# ---------------------------------------------------------------------------


def is_resolved(reply: str) -> bool:
    """Return True if the bot reply signals a conversation has been wrapped up."""
    lower = reply.lower()
    return any(phrase in lower for phrase in _RESOLUTION_PHRASES)


def _bot_just_asked_meeting_question(history: list) -> bool:
    """Return True if the most recent bot message contained the meeting/agent question."""
    for msg in reversed(history):
        if msg.get("role") == "assistant":
            content = (msg.get("content") or "").lower()
            return any(p in content for p in _MEETING_QUESTION_PHRASES)
    return False


def _bot_just_offered_agent(history: list) -> bool:
    """Return True if the most recent bot message explicitly offered the agent option."""
    for msg in reversed(history):
        if msg.get("role") == "assistant":
            content = (msg.get("content") or "").lower()
            return any(p in content for p in _AGENT_OFFER_PHRASES)
    return False


def wants_meeting(message: str, history: list | None = None) -> bool:
    """
    Return True if the customer's message indicates they want to book a meeting.

    Ambiguous affirmatives (yes/ok/sure) only count when the bot just asked
    the meeting-or-agent question, to avoid false positives.
    """
    lower = message.lower()
    if any(_kw_match(kw, lower) for kw in _MEETING_KEYWORDS):
        matched = {kw for kw in _MEETING_KEYWORDS if _kw_match(kw, lower)}
        non_ambiguous = matched - _AMBIGUOUS_AFFIRMATIVES
        if non_ambiguous:
            return True
        # Only ambiguous words matched — require prior context.
        if history and _bot_just_asked_meeting_question(history):
            return True
    return False


def wants_escalation(message: str, history: list | None = None) -> bool:
    """
    Return True if the customer explicitly wants to speak to a human agent.

    Ambiguous affirmatives only count when the bot just offered the agent option.
    """
    lower = message.lower()
    if any(_kw_match(kw, lower) for kw in _ESCALATION_KEYWORDS):
        return True
    # Ambiguous affirmatives only count with agent-offer context.
    if any(_kw_match(kw, lower) for kw in _AMBIGUOUS_AFFIRMATIVES):
        if history and _bot_just_offered_agent(history):
            return True
    return False


def ai_scheduling_manually(reply: str) -> bool:
    """Return True if OpenAI is trying to collect a date/time from the customer."""
    lower = reply.lower()
    return any(p in lower for p in _AI_SCHEDULING_PHRASES)
