"""
test_health.py — Tests for the GET /health endpoint.
"""

import pytest


class TestHealth:
    async def test_healthy_returns_200(self, client, mock_conn):
        """Returns 200 with status:ok when the DB is reachable."""
        mock_conn.fetchval.return_value = 1
        resp = await client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["database"] == "connected"

    async def test_degraded_returns_503(self, client, mock_pool, mock_conn):
        """Returns 503 with status:degraded when the DB throws."""
        from contextlib import asynccontextmanager
        import database

        @asynccontextmanager
        async def broken_acquire():
            raise ConnectionError("DB is down")
            yield  # unreachable but satisfies the generator protocol

        mock_pool.acquire = broken_acquire
        database.pool = mock_pool

        resp = await client.get("/health")
        assert resp.status_code == 503
        data = resp.json()
        assert data["status"] == "degraded"
        assert data["database"] == "unreachable"

    async def test_health_no_auth_required(self, client):
        """Health endpoint must be reachable without any credentials."""
        resp = await client.get("/health")
        # 200 or 503 are both acceptable — 401/403 are not
        assert resp.status_code in (200, 503)
