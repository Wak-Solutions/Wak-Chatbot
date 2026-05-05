"""prompt.py — public system-prompt API; re-exports loader, language, builder, and default constant."""

from _prompt_default import DEFAULT_SYSTEM_PROMPT
from _prompt_language import _LANGUAGE_OVERRIDE, detect_language
from _prompt_cache import _cache, _CACHE_TTL, get_system_prompt, invalidate_prompt_cache
from _prompt_builder import build_system_prompt
