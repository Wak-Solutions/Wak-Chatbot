"""main.py — FastAPI app entry point: lifespan setup, router wiring, and the uvicorn-bound `app`."""

import logging
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

import agent
import database
import notifications
import transcribe as transcribe_mod
import whatsapp
from deps import require_webhook_secret  # re-exported for back-compat
from routes.audio import router as audio_router
from routes.health import router as health_router
from routes.send import router as send_router
from routes.webhook import router as webhook_router
from workers.audio import process_audio_message  # re-exported for back-compat
from workers.link_delivery import _link_delivery_loop  # re-exported for back-compat
from workers.text import process_message  # re-exported for back-compat

# Structured logging — format: timestamp | LEVEL | module | message
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Creates DB pool and shared HTTP client on startup, closes on shutdown."""
    logger.info("Starting up — creating database connection pool")
    await database.create_pool()
    logger.info("Database pool ready")

    http_client = httpx.AsyncClient(
        timeout=30.0,
        limits=httpx.Limits(max_connections=20),
    )
    whatsapp.set_client(http_client)
    notifications.set_client(http_client)
    transcribe_mod.set_client(http_client)
    agent.set_http_client(http_client)

    # delivery_task = asyncio.create_task(_link_delivery_loop())
    # logger.info("Meeting link delivery job started")
    yield
    # delivery_task.cancel()
    # try:
    #     await delivery_task
    # except asyncio.CancelledError:
    #     pass
    await http_client.aclose()
    logger.info("Shutting down — closing database connection pool")
    await database.close_pool()
    logger.info("Database pool closed")


app = FastAPI(lifespan=lifespan)
app.include_router(health_router)
app.include_router(webhook_router)
app.include_router(send_router)
app.include_router(audio_router)
