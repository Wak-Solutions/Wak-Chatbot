"""
test_prompt.py — Tests for the system prompt cache in prompt.py.
"""

import time
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest

import database
import prompt
from prompt import DEFAULT_SYSTEM_PROMPT, detect_language, get_system_prompt, invalidate_prompt_cache


@pytest.fixture(autouse=True)
def clear_cache():
    """Clear the prompt cache before and after each test to prevent state leakage."""
    invalidate_prompt_cache()
    yield
    invalidate_prompt_cache()


class TestGetSystemPrompt:
    async def test_loads_prompt_from_db(self, mock_conn):
        mock_conn.fetchrow.return_value = {"system_prompt": "Custom prompt from DB"}
        result = await get_system_prompt(company_id=1)
        assert result == "Custom prompt from DB"

    async def test_returns_default_when_db_row_is_none(self, mock_conn):
        mock_conn.fetchrow.return_value = None
        result = await get_system_prompt(company_id=1)
        assert result == DEFAULT_SYSTEM_PROMPT

    async def test_returns_default_when_db_unreachable(self, mock_pool):
        """When the DB raises, fall back to the hardcoded default."""
        @asynccontextmanager
        async def broken_acquire():
            raise ConnectionError("DB down")
            yield

        mock_pool.acquire = broken_acquire
        database.pool = mock_pool

        result = await get_system_prompt(company_id=1)
        assert result == DEFAULT_SYSTEM_PROMPT

    async def test_cache_hit_within_ttl(self, mock_conn):
        """Second call within 60 s must NOT hit the DB again."""
        mock_conn.fetchrow.return_value = {"system_prompt": "Cached prompt"}

        first = await get_system_prompt(company_id=1)
        second = await get_system_prompt(company_id=1)

        assert first == second == "Cached prompt"
        # fetchrow called only once despite two get_system_prompt() calls
        assert mock_conn.fetchrow.call_count == 1

    async def test_cache_refreshes_after_invalidation(self, mock_conn):
        """invalidate_prompt_cache() should force a DB reload on next call."""
        mock_conn.fetchrow.return_value = {"system_prompt": "Version 1"}
        await get_system_prompt(company_id=1)

        invalidate_prompt_cache(company_id=1)

        mock_conn.fetchrow.return_value = {"system_prompt": "Version 2"}
        result = await get_system_prompt(company_id=1)

        assert result == "Version 2"
        assert mock_conn.fetchrow.call_count == 2

    async def test_stale_cache_used_when_db_down(self, mock_conn, mock_pool):
        """When cache is populated but DB then fails, return stale cache not default."""
        mock_conn.fetchrow.return_value = {"system_prompt": "Stale prompt"}
        await get_system_prompt(company_id=99)  # populate cache

        # Now break the DB
        @asynccontextmanager
        async def broken_acquire():
            raise RuntimeError("gone")
            yield

        mock_pool.acquire = broken_acquire
        database.pool = mock_pool

        # Manually expire the cache entry
        prompt._cache[99] = (prompt._cache[99][0], 0.0)  # set timestamp to epoch

        result = await get_system_prompt(company_id=99)
        assert result == "Stale prompt"  # stale is preferred over default


class TestDetectLanguage:
    def test_english_only(self):
        assert detect_language("hello") == "English"

    def test_arabic_only(self):
        assert detect_language("مرحبا") == "Arabic"

    def test_mixed_arabic_wins(self):
        """Arabic characters present → Arabic, even if most text is English."""
        assert detect_language("hello مرحبا") == "Arabic"

    def test_empty_string(self):
        assert detect_language("") is None

    def test_single_digit(self):
        assert detect_language("2") is None

    def test_multiple_digits(self):
        assert detect_language("123") is None

    def test_punctuation_only(self):
        assert detect_language("!") is None

    def test_emoji_only(self):
        assert detect_language("😊") is None

    def test_numbers_and_punctuation(self):
        assert detect_language("123 !@#") is None


class TestLanguageOverride:
    async def test_english_message_appends_english_override(self, mock_conn):
        mock_conn.fetchrow.return_value = {"system_prompt": "Base prompt"}
        result = await get_system_prompt(company_id=1, current_message="hello")
        assert "OVERRIDE" in result
        assert "English" in result.split("OVERRIDE")[1]
        assert "Arabic" not in result.split("OVERRIDE")[1]

    async def test_arabic_message_appends_arabic_override(self, mock_conn):
        mock_conn.fetchrow.return_value = {"system_prompt": "Base prompt"}
        result = await get_system_prompt(company_id=1, current_message="مرحبا")
        assert "OVERRIDE" in result
        assert "Arabic" in result.split("OVERRIDE")[1]

    async def test_no_message_no_override(self, mock_conn):
        mock_conn.fetchrow.return_value = {"system_prompt": "Base prompt"}
        result = await get_system_prompt(company_id=1)
        assert result == "Base prompt"
        assert "OVERRIDE" not in result

    async def test_digits_only_no_override(self, mock_conn):
        mock_conn.fetchrow.return_value = {"system_prompt": "Base prompt"}
        result = await get_system_prompt(company_id=1, current_message="2")
        assert result == "Base prompt"
        assert "OVERRIDE" not in result

    async def test_override_does_not_pollute_cache(self, mock_conn):
        """The language override must not be stored in the cache."""
        mock_conn.fetchrow.return_value = {"system_prompt": "Base prompt"}
        await get_system_prompt(company_id=1, current_message="hello")
        # Cache entry must be the raw prompt, not the override-appended version
        assert prompt._cache[1][0] == "Base prompt"

    async def test_second_call_different_language_gets_correct_override(self, mock_conn):
        """Two consecutive calls with different languages both get correct overrides."""
        mock_conn.fetchrow.return_value = {"system_prompt": "Base"}
        english_result = await get_system_prompt(company_id=1, current_message="hello")
        arabic_result = await get_system_prompt(company_id=1, current_message="مرحبا")
        assert "English" in english_result.split("OVERRIDE")[1]
        assert "Arabic" in arabic_result.split("OVERRIDE")[1]


class TestInvalidatePromptCache:
    async def test_invalidate_specific_company(self, mock_conn):
        mock_conn.fetchrow.return_value = {"system_prompt": "Prompt A"}
        await get_system_prompt(company_id=1)
        await get_system_prompt(company_id=2)

        invalidate_prompt_cache(company_id=1)

        assert 1 not in prompt._cache
        assert 2 in prompt._cache

    async def test_invalidate_all(self, mock_conn):
        mock_conn.fetchrow.return_value = {"system_prompt": "Prompt"}
        await get_system_prompt(company_id=1)
        await get_system_prompt(company_id=2)

        invalidate_prompt_cache()  # no argument = clear all

        assert prompt._cache == {}
