"""webhook.py — Meta webhook endpoints: GET verify + POST receive (with per-company signature check)."""

import hashlib
import hmac
import json
import logging

from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import JSONResponse, PlainTextResponse

import database
from config import VERIFY_TOKEN
from notifications import mask_phone
from workers.audio import process_audio_message
from workers.text import process_message

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/webhook")
async def verify_webhook(request: Request):
    """Meta webhook verification endpoint."""
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    logger.info("Webhook verification request — mode: %s", mode)

    if mode == "subscribe" and token == VERIFY_TOKEN:
        logger.info("Webhook verified successfully")
        return PlainTextResponse(content=challenge, status_code=200)

    logger.warning("Webhook verification failed — token mismatch")
    return PlainTextResponse(content="Forbidden", status_code=403)


@router.post("/webhook")
async def receive_message(request: Request, background_tasks: BackgroundTasks):
    """
    Meta incoming-message webhook.
    Returns 200 immediately, processes in background to prevent Meta retries.

    Resolves company_id from the WhatsApp phone_number_id in the webhook metadata.
    Falls back to company_id=1 if the phone number is not yet registered.
    """
    # ── Signature verification (per-company) ──────────────────────────
    raw_body = await request.body()

    signature_header = request.headers.get("X-Hub-Signature-256", "")
    if not signature_header:
        logger.warning("Webhook POST rejected — missing X-Hub-Signature-256 header")
        return JSONResponse(content={"error": "Forbidden"}, status_code=403)

    try:
        _prelim = json.loads(raw_body)
        _entry = _prelim.get("entry", [])
        _changes = _entry[0].get("changes", []) if _entry else []
        _value = _changes[0].get("value", {}) if _changes else {}
        _pnid = _value.get("metadata", {}).get("phone_number_id", "")
    except Exception:
        logger.warning("Webhook POST dropped — malformed JSON body")
        return JSONResponse(content={"status": "ok"}, status_code=200)

    if not _pnid:
        logger.info("Webhook with no phone_number_id — likely a status update, accepting")
        return JSONResponse(content={"status": "ok"}, status_code=200)

    app_secret = await database.get_app_secret_by_phone_number_id(_pnid)
    if not app_secret:
        logger.warning(
            "Webhook POST rejected — no app_secret registered for phone_number_id=%s",
            _pnid,
        )
        return JSONResponse(content={"error": "Forbidden"}, status_code=403)

    expected_sig = "sha256=" + hmac.new(
        app_secret.encode(),
        raw_body,
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected_sig, signature_header):
        logger.warning(
            "Webhook POST rejected — signature mismatch for phone_number_id=%s",
            _pnid,
        )
        return JSONResponse(content={"error": "Forbidden"}, status_code=403)
    # ── End signature verification ────────────────────────────────────

    body = _prelim

    try:
        entry = body.get("entry", [])
        changes = entry[0].get("changes", []) if entry else []
        value = changes[0].get("value", {}) if changes else {}

        messages_list = value.get("messages", [])
        if not messages_list:
            logger.info("No messages in payload — likely a status update, ignoring")
            return JSONResponse(content={"status": "ok"}, status_code=200)

        phone_number_id = value.get("metadata", {}).get("phone_number_id", "")
        company_id = await database.get_company_by_phone_number_id(phone_number_id)
        if company_id is None:
            return JSONResponse(content={"status": "unroutable"}, status_code=200)

        creds = await database.get_company_whatsapp_creds(company_id)
        if creds is None:
            logger.error(
                "Company %d has no WhatsApp credentials — cannot send replies",
                company_id,
            )
            return JSONResponse(content={"status": "no_creds"}, status_code=200)

        message = messages_list[0]
        msg_type = message.get("type")
        customer_phone = message.get("from")

        if not customer_phone:
            logger.warning("Webhook message missing 'from' field — ignoring")
            return JSONResponse(content={"status": "ok"}, status_code=200)

        if msg_type == "text":
            message_text = message.get("text", {}).get("body")
            if not message_text:
                logger.warning(
                    "Text message with empty body — phone: %s",
                    mask_phone(customer_phone),
                )
                return JSONResponse(content={"status": "ok"}, status_code=200)
            logger.info(
                "Message received — phone: %s, type: text, company_id: %d",
                mask_phone(customer_phone),
                company_id,
            )
            background_tasks.add_task(process_message, customer_phone, message_text, company_id, creds)

        elif msg_type == "audio":
            audio_data = message.get("audio", {})
            media_id = audio_data.get("id")
            mime_type = audio_data.get("mime_type", "audio/ogg")
            if not media_id:
                logger.warning(
                    "Audio message missing media ID — phone: %s",
                    mask_phone(customer_phone),
                )
                return JSONResponse(content={"status": "ok"}, status_code=200)
            logger.info(
                "Message received — phone: %s, type: audio, mime: %s, company_id: %d",
                mask_phone(customer_phone),
                mime_type,
                company_id,
            )
            background_tasks.add_task(
                process_audio_message, customer_phone, media_id, mime_type, company_id, creds
            )

        else:
            logger.info(
                "Unsupported message type — phone: %s, type: %s",
                mask_phone(customer_phone),
                msg_type,
            )

    except (IndexError, KeyError, TypeError) as exc:
        logger.error("Failed to parse webhook payload: %s", exc, exc_info=True)

    return JSONResponse(content={"status": "ok"}, status_code=200)
