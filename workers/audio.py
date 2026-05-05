"""audio.py — background worker that downloads, transcribes, and replies to an inbound voice note."""

import logging

import agent
import database
import memory
import transcribe as transcribe_mod
import whatsapp
from notifications import mask_phone

logger = logging.getLogger(__name__)


async def process_audio_message(customer_phone: str, media_id: str, mime_type: str, company_id: int, creds: dict):
    """
    Handle an incoming WhatsApp voice note end-to-end:
    1. Download audio from Meta's CDN.
    2. Store audio bytes in the voice_notes table.
    3. Transcribe with OpenAI Whisper.
    4. Save the inbound message with media metadata.
    5. Feed the transcription into the normal bot flow.
    """
    try:
        logger.info(
            "Processing voice note — phone: %s, mime: %s",
            mask_phone(customer_phone),
            mime_type,
        )

        # Step 1: Download
        try:
            audio_bytes, actual_mime = await transcribe_mod.download_media(media_id, token=creds["token"])
        except ValueError as exc:
            if "too large" in str(exc).lower():
                logger.warning(
                    "Voice note rejected (too large) — phone: %s",
                    mask_phone(customer_phone),
                )
                await whatsapp.send_message(
                    to=customer_phone,
                    text=(
                        "Sorry, your voice message is too long for me to process. "
                        "Could you send a shorter message (under 3 minutes) "
                        "or type your question instead?"
                    ),
                    token=creds["token"],
                    phone_id=creds["phone_id"],
                )
            else:
                raise
            return

        # Step 2: Store audio in DB
        audio_id = await database.store_voice_note(audio_bytes, actual_mime, company_id)
        app_url = await database.get_company_app_url(company_id)
        if app_url is None:
            logger.error(
                "Audio handling — app_url not set for company %d, cannot build media_url",
                company_id,
            )
            return
        media_url = f"{app_url}/api/voice-notes/{audio_id}"

        # Step 3: Transcribe
        try:
            transcription = await transcribe_mod.transcribe(audio_bytes, actual_mime)
        except Exception as exc:
            logger.error(
                "Whisper transcription failed — phone: %s, error: %s",
                mask_phone(customer_phone),
                exc,
                exc_info=True,
            )
            await memory.save_message(
                customer_phone=customer_phone,
                direction="inbound",
                message_text="[Voice message — transcription unavailable]",
                sender="customer",
                media_type="audio",
                media_url=media_url,
                transcription=None,
                company_id=company_id,
            )
            await whatsapp.send_message(
                to=customer_phone,
                text=(
                    "Sorry, I couldn't process your voice message. "
                    "Could you type your question instead?"
                ),
                token=creds["token"],
                phone_id=creds["phone_id"],
            )
            return

        if not transcription:
            logger.info(
                "Whisper returned empty transcription — phone: %s",
                mask_phone(customer_phone),
            )
            await memory.save_message(
                customer_phone=customer_phone,
                direction="inbound",
                message_text="[Voice message — no speech detected]",
                sender="customer",
                media_type="audio",
                media_url=media_url,
                transcription="",
                company_id=company_id,
            )
            await whatsapp.send_message(
                to=customer_phone,
                text=(
                    "I received your voice message but couldn't make out any words. "
                    "Could you type your question instead?"
                ),
                token=creds["token"],
                phone_id=creds["phone_id"],
            )
            return

        # Step 4: Save inbound with full media metadata
        await memory.save_message(
            customer_phone=customer_phone,
            direction="inbound",
            message_text=transcription,
            sender="customer",
            media_type="audio",
            media_url=media_url,
            transcription=transcription,
            company_id=company_id,
        )

        # Step 5: Run transcription through the normal bot flow
        reply, meeting_message = await agent.get_reply(
            customer_phone=customer_phone,
            new_message=transcription,
            _save_inbound=False,
            company_id=company_id,
        )

        await whatsapp.send_message(to=customer_phone, text=reply, token=creds["token"], phone_id=creds["phone_id"])
        await memory.save_message(
            customer_phone=customer_phone,
            direction="outbound",
            message_text=reply,
            sender="ai",
            company_id=company_id,
        )
        logger.info(
            "Reply sent after voice note — phone: %s, type: text",
            mask_phone(customer_phone),
        )

        if meeting_message:
            await whatsapp.send_message(to=customer_phone, text=meeting_message, token=creds["token"], phone_id=creds["phone_id"])
            await memory.save_message(
                customer_phone=customer_phone,
                direction="outbound",
                message_text=meeting_message,
                sender="ai",
                company_id=company_id,
            )

    except Exception as exc:
        logger.error(
            "Failed to process voice note — phone: %s, error: %s",
            mask_phone(customer_phone),
            exc,
            exc_info=True,
        )
