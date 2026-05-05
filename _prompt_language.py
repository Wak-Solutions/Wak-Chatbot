"""_prompt_language.py — language detection and the override snippet appended to prompts."""

import re

_LANGUAGE_OVERRIDE = (
    "\n\nOVERRIDE — CURRENT MESSAGE LANGUAGE:\n"
    "The customer's current message is in {language}.\n"
    "You MUST reply in {language} only. "
    "This overrides all conversation history."
)


def detect_language(text: str) -> str | None:
    """Return 'Arabic', 'English', or None (digits/punctuation/emoji — no language signal)."""
    if re.search(r"[؀-ۿ]", text):
        return "Arabic"
    if re.search(r"[a-zA-Z]", text):
        return "English"
    return None
