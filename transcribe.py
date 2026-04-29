"""
transcribe.py — download WhatsApp voice notes and transcribe with Whisper.
"""

import logging
from io import BytesIO

import httpx
from openai import AsyncOpenAI

from config import OPENAI_API_KEY

logger = logging.getLogger(__name__)

_http_client: httpx.AsyncClient | None = None


def set_client(client: httpx.AsyncClient) -> None:
    global _http_client
    _http_client = client


_GRAPH_VERSION = "v21.0"

# Whisper hard limit is 25 MB. WhatsApp's own limit for voice notes is 16 MB,
# so we'll never hit 25 MB — we reject at 20 MB as a safety margin.
_MAX_AUDIO_BYTES = 20 * 1024 * 1024  # 20 MB

_openai = AsyncOpenAI(api_key=OPENAI_API_KEY)

_MIME_TO_EXT: dict[str, str] = {
    "audio/ogg": "ogg",
    "audio/ogg; codecs=opus": "ogg",
    "audio/mpeg": "mp3",
    "audio/mp4": "mp4",
    "audio/aac": "aac",
    "audio/amr": "amr",
    "audio/wav": "wav",
    "audio/webm": "webm",
}


def _ext(mime_type: str) -> str:
    """Return a Whisper-compatible extension for a given MIME type."""
    base = mime_type.split(";")[0].strip().lower()
    return _MIME_TO_EXT.get(base, "ogg")


async def download_media(media_id: str, *, token: str) -> tuple[bytes, str]:
    """
    Download a WhatsApp voice note from Meta's CDN.

    Step 1: GET /v21.0/{media_id} → resolve CDN URL and MIME type.
    Step 2: GET {cdn_url}         → download raw audio bytes.

    Args:
        media_id: The Meta media ID returned in the inbound webhook.
        token:    The owning company's WhatsApp access token.

    Returns:
        (audio_bytes, mime_type)

    Raises:
        ValueError: If the file is too large for Whisper.
        httpx.*:    If Meta's API returns an error.
    """
    auth_headers = {"Authorization": f"Bearer {token}"}

    _client = _http_client or httpx.AsyncClient()
    _is_temp = _http_client is None
    try:
        # Step 1 — resolve the media ID to a CDN URL
        meta_resp = await _client.get(
            f"https://graph.facebook.com/{_GRAPH_VERSION}/{media_id}",
            headers=auth_headers,
            timeout=10.0,
        )
        meta_resp.raise_for_status()
        meta = meta_resp.json()

        cdn_url = meta.get("url")
        mime_type = meta.get("mime_type", "audio/ogg")
        file_size = meta.get("file_size", 0)

        logger.info(
            "Media metadata — media_id: %s, mime: %s, size_bytes: %s",
            media_id,
            mime_type,
            file_size or "unknown",
        )

        if not cdn_url:
            raise ValueError(f"No CDN URL returned for media_id={media_id}")

        if file_size and file_size > _MAX_AUDIO_BYTES:
            logger.warning(
                "Audio too large before download — size_bytes: %d, limit: %d",
                file_size,
                _MAX_AUDIO_BYTES,
            )
            raise ValueError(
                f"Voice note too large: {file_size:,} bytes (limit {_MAX_AUDIO_BYTES:,} bytes)"
            )

        # Step 2 — download the audio bytes
        audio_resp = await _client.get(
            cdn_url,
            headers=auth_headers,
            timeout=30.0,
            follow_redirects=True,
        )
        audio_resp.raise_for_status()
        audio_bytes = audio_resp.content
    finally:
        if _is_temp:
            await _client.aclose()

    if len(audio_bytes) > _MAX_AUDIO_BYTES:
        logger.warning(
            "Audio too large after download — size_bytes: %d, limit: %d",
            len(audio_bytes),
            _MAX_AUDIO_BYTES,
        )
        raise ValueError(
            f"Voice note too large after download: {len(audio_bytes):,} bytes"
        )

    logger.info(
        "Audio downloaded — media_id: %s, size_bytes: %d, mime: %s",
        media_id,
        len(audio_bytes),
        mime_type,
    )
    return audio_bytes, mime_type


async def transcribe(audio_bytes: bytes, mime_type: str) -> str:
    """
    Transcribe audio bytes using OpenAI Whisper.

    Whisper automatically detects the language — no language hint needed.

    Returns:
        Stripped transcription string. Empty string if no speech detected.

    Raises:
        openai.APIError: On Whisper API failures.
    """
    ext = _ext(mime_type)
    size_bytes = len(audio_bytes)

    logger.info(
        "Whisper request — model: whisper-1, size_bytes: %d, ext: %s",
        size_bytes,
        ext,
    )

    audio_file = BytesIO(audio_bytes)
    audio_file.name = f"voice.{ext}"

    try:
        response = await _openai.audio.transcriptions.create(
            model="whisper-1",
            file=audio_file,
        )
        text = (response.text or "").strip()

        if text:
            logger.info(
                "Whisper success — model: whisper-1, size_bytes: %d, result_chars: %d",
                size_bytes,
                len(text),
            )
        else:
            logger.info(
                "Whisper returned empty transcription — model: whisper-1, size_bytes: %d",
                size_bytes,
            )
        return text

    except Exception as exc:
        logger.error(
            "Whisper failed — model: whisper-1, size_bytes: %d, error: %s",
            size_bytes,
            exc,
            exc_info=True,
        )
        raise
