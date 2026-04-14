"""
test_prompt.py — Tests for the system prompt cache in prompt.py.
"""

import time
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest

import database
import prompt
from prompt import DEFAULT_SYSTEM_PROMPT, get_system_prompt, invalidate_prompt_cache


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
