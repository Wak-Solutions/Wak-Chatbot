"""
test_database.py — Tests for database.py helpers.
"""

import pytest

import database


class TestGetWebhookSecretByCompanyId:
    async def test_returns_secret_for_active_company(self, mock_conn):
        mock_conn.fetchrow.return_value = {"webhook_secret": "abc123secret"}
        result = await database.get_webhook_secret_by_company_id(1)
        assert result == "abc123secret"

    async def test_returns_none_for_unknown_company(self, mock_conn):
        mock_conn.fetchrow.return_value = None
        result = await database.get_webhook_secret_by_company_id(999)
        assert result is None

    async def test_returns_none_when_db_raises(self, mock_conn):
        mock_conn.fetchrow.side_effect = RuntimeError("connection lost")
        result = await database.get_webhook_secret_by_company_id(1)
        assert result is None

    async def test_queries_by_company_id(self, mock_conn):
        mock_conn.fetchrow.return_value = {"webhook_secret": "mysecret"}
        await database.get_webhook_secret_by_company_id(42)
        call_args = mock_conn.fetchrow.call_args
        assert 42 in call_args.args


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
