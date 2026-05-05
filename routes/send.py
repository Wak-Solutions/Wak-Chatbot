"""send.py — POST /send endpoint used by the dashboard to deliver a manual agent reply."""

import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

import database
import memory
import whatsapp
from deps import require_webhook_secret
from notifications import mask_phone

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/send")
async def send_agent_message(request: Request, _: None = Depends(require_webhook_secret)):
    """
    Called by the agent dashboard when an agent sends a manual reply.
    Validates the webhook secret, sends via WhatsApp, saves with sender='agent'.
    """
    body = await request.json()
    customer_phone = body.get("customer_phone")
    message_text = body.get("message")

    incoming_secret = request.headers.get("x-webhook-secret", "")
    company = await database.get_company_by_webhook_secret(incoming_secret)
    if not company:
        return JSONResponse(content={"error": "Unauthorized"}, status_code=401)
    company_id = company["id"]

    if not customer_phone or not message_text:
        return JSONResponse(content={"error": "Missing fields"}, status_code=400)

    creds = await database.get_company_whatsapp_creds(company_id)
    if creds is None:
        logger.error("/send — company %d has no WhatsApp credentials", company_id)
        return JSONResponse(content={"error": "WhatsApp credentials not configured"}, status_code=503)

    try:
        await whatsapp.send_message(to=customer_phone, text=message_text, token=creds["token"], phone_id=creds["phone_id"])
        await memory.save_message(
            customer_phone=customer_phone,
            direction="outbound",
            message_text=message_text,
            sender="agent",
            company_id=company_id,
        )
        logger.info(
            "Agent message sent — phone: %s, type: text",
            mask_phone(customer_phone),
        )
        return JSONResponse(content={"status": "sent"}, status_code=200)
    except Exception as exc:
        logger.error(
            "Failed to send agent message — phone: %s, error: %s",
            mask_phone(customer_phone),
            exc,
            exc_info=True,
        )
        return JSONResponse(content={"error": "Internal error"}, status_code=500)
