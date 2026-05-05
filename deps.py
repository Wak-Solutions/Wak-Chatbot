"""deps.py — shared FastAPI dependencies (timing-safe webhook secret check)."""

import secrets

from fastapi import Header, HTTPException

from config import WEBHOOK_SECRET


async def require_webhook_secret(x_webhook_secret: str = Header(default="")) -> None:
    if not WEBHOOK_SECRET or not secrets.compare_digest(x_webhook_secret, WEBHOOK_SECRET):
        raise HTTPException(status_code=403, detail="Forbidden")
