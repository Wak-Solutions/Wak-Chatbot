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


class TestGetCompanyByPhoneNumberIdCache:
    @pytest.fixture(autouse=True)
    def _clear_cache(self):
        database._company_cache.clear()
        yield
        database._company_cache.clear()

    async def test_cached_value_returned_within_ttl(self, mock_conn):
        mock_conn.fetchrow.return_value = {"id": 7}
        first = await database.get_company_by_phone_number_id("PHN-A")
        assert first == 7
        assert mock_conn.fetchrow.await_count == 1

        # Second call within TTL → no DB round-trip
        second = await database.get_company_by_phone_number_id("PHN-A")
        assert second == 7
        assert mock_conn.fetchrow.await_count == 1

    async def test_expired_entry_triggers_fresh_db_lookup(self, mock_conn, monkeypatch):
        mock_conn.fetchrow.return_value = {"id": 9}
        await database.get_company_by_phone_number_id("PHN-B")
        assert mock_conn.fetchrow.await_count == 1

        # Simulate cache entry aged past TTL
        cached_id, cached_at = database._company_cache["PHN-B"]
        database._company_cache["PHN-B"] = (cached_id, cached_at - (database._COMPANY_CACHE_TTL + 1))

        await database.get_company_by_phone_number_id("PHN-B")
        assert mock_conn.fetchrow.await_count == 2

    async def test_cache_refreshed_after_expiry_with_new_timestamp(self, mock_conn):
        mock_conn.fetchrow.return_value = {"id": 4}
        await database.get_company_by_phone_number_id("PHN-C")
        original_id, original_at = database._company_cache["PHN-C"]

        # Force expiry
        database._company_cache["PHN-C"] = (original_id, original_at - (database._COMPANY_CACHE_TTL + 5))

        await database.get_company_by_phone_number_id("PHN-C")
        refreshed_id, refreshed_at = database._company_cache["PHN-C"]
        assert refreshed_id == 4
        assert refreshed_at > original_at


class TestGetCompanyAppUrl:
    async def test_returns_stripped_url_for_known_company(self, mock_conn):
        mock_conn.fetchrow.return_value = {"app_url": "https://app.example.com/"}
        result = await database.get_company_app_url(1)
        assert result == "https://app.example.com"

    async def test_returns_url_without_trailing_slash(self, mock_conn):
        mock_conn.fetchrow.return_value = {"app_url": "https://app.example.com"}
        result = await database.get_company_app_url(1)
        assert result == "https://app.example.com"

    async def test_returns_none_when_row_not_found(self, mock_conn):
        mock_conn.fetchrow.return_value = None
        result = await database.get_company_app_url(99)
        assert result is None

    async def test_returns_none_when_app_url_is_null(self, mock_conn):
        mock_conn.fetchrow.return_value = {"app_url": None}
        result = await database.get_company_app_url(1)
        assert result is None

    async def test_returns_none_when_app_url_is_empty_string(self, mock_conn):
        mock_conn.fetchrow.return_value = {"app_url": ""}
        result = await database.get_company_app_url(1)
        assert result is None

    async def test_returns_none_on_db_error(self, mock_conn):
        mock_conn.fetchrow.side_effect = RuntimeError("connection lost")
        result = await database.get_company_app_url(1)
        assert result is None

    async def test_queries_by_company_id(self, mock_conn):
        mock_conn.fetchrow.return_value = {"app_url": "https://x.example.com"}
        await database.get_company_app_url(42)
        call_args = mock_conn.fetchrow.call_args
        assert 42 in call_args.args
