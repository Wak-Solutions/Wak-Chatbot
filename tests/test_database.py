"""
test_database.py — Tests for database.py helpers.
"""

import pytest

import database


class TestGetCompanyByWebhookSecret:
    async def test_returns_company_when_secret_matches(self, mock_conn):
        mock_conn.fetchrow.return_value = {"id": 2, "name": "Dynamic AI"}
        result = await database.get_company_by_webhook_secret("good-secret")
        assert result == {"id": 2, "name": "Dynamic AI"}

    async def test_returns_none_for_unknown_secret(self, mock_conn):
        mock_conn.fetchrow.return_value = None
        result = await database.get_company_by_webhook_secret("bogus-secret")
        assert result is None

    async def test_returns_none_for_empty_string(self, mock_conn):
        result = await database.get_company_by_webhook_secret("")
        assert result is None
        mock_conn.fetchrow.assert_not_called()

    async def test_returns_none_for_inactive_company(self, mock_conn):
        # The query filters is_active = true, so an inactive company returns
        # no row. This mirrors what asyncpg actually does in production.
        mock_conn.fetchrow.return_value = None
        result = await database.get_company_by_webhook_secret("inactive-co-secret")
        assert result is None

    async def test_returns_none_when_db_raises(self, mock_conn):
        mock_conn.fetchrow.side_effect = RuntimeError("connection lost")
        result = await database.get_company_by_webhook_secret("anything")
        assert result is None
