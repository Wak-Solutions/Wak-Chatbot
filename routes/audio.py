"""audio.py — GET /audio/{audio_id} endpoint that streams stored voice notes (auth required)."""

import logging
import uuid

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response

import database
from deps import require_webhook_secret

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/audio/{audio_id}")
async def serve_audio(audio_id: str, request: Request, _: None = Depends(require_webhook_secret)):
    """
    Stream a stored voice note. Protected by x-webhook-secret header.
    """
    try:
        uuid.UUID(audio_id)
    except ValueError:
        return JSONResponse(content={"error": "Not found"}, status_code=404)

    company = await database.get_company_by_webhook_secret(
        request.headers.get("x-webhook-secret", "")
    )
    if not company:
        return JSONResponse(content={"error": "Not found"}, status_code=404)

    row = await database.get_voice_note(audio_id, company["id"])
    if row is None:
        logger.warning("Audio not found — id: %s", audio_id)
        return JSONResponse(content={"error": "Not found"}, status_code=404)
    return Response(
        content=row["audio_data"],
        media_type=row["mime_type"],
        headers={
            "Cache-Control": "public, max-age=86400",
            "Access-Control-Allow-Origin": "*",
        },
    )
