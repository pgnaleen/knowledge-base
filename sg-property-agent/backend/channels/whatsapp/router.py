"""WhatsApp webhook router (GET verification + POST message handler)."""

import hashlib
import hmac
import json
import os

import structlog
from fastapi import APIRouter, BackgroundTasks, Request, Response

from channels.whatsapp.meta_client import MetaApiClient
from graph.main import run as graph_run

log = structlog.get_logger()


def _verify_signature(raw_body: bytes, sig_header: str) -> bool:
    """
    Verify the X-Hub-Signature-256 header sent by Meta.
    Returns True (skip check) if WHATSAPP_APP_SECRET is not set (dev mode).
    """
    secret = os.environ.get("WHATSAPP_APP_SECRET", "")
    if not secret:
        return True
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(f"sha256={expected}", sig_header)


def create_whatsapp_router() -> APIRouter:
    router = APIRouter()
    _meta = MetaApiClient()

    @router.get("/")
    async def verify_webhook(request: Request) -> Response:
        """Handle Meta's webhook verification GET handshake."""
        mode = request.query_params.get("hub.mode")
        token = request.query_params.get("hub.verify_token")
        challenge = request.query_params.get("hub.challenge")

        if mode == "subscribe" and token == os.environ["WHATSAPP_VERIFY_TOKEN"]:
            log.info("whatsapp_webhook_verified")
            return Response(content=challenge, media_type="text/plain", status_code=200)

        log.warning("whatsapp_webhook_verification_failed", mode=mode)
        return Response(status_code=403)

    @router.post("/")
    async def receive_message(request: Request, background_tasks: BackgroundTasks) -> Response:
        """Handle incoming WhatsApp messages — verify HMAC, return 200, process in background."""
        raw_body = await request.body()

        sig_header = request.headers.get("X-Hub-Signature-256", "")
        if not _verify_signature(raw_body, sig_header):
            log.warning("whatsapp_hmac_verification_failed")
            return Response(status_code=401)

        try:
            body = json.loads(raw_body)
        except json.JSONDecodeError:
            return Response(status_code=400)

        log.info("whatsapp_webhook_received", object_type=body.get("object"))

        if body.get("object") != "whatsapp_business_account":
            return Response(status_code=404)

        try:
            entry = body.get("entry", [])
            if not entry:
                return Response(status_code=200)

            changes = entry[0].get("changes", [])
            if not changes:
                return Response(status_code=200)

            value = changes[0].get("value", {})
            messages = value.get("messages")

            if not messages:
                return Response(status_code=200)  # status update, not a message

            message = messages[0]
            sender_phone = message.get("from")
            message_id = message.get("id")
            message_type = message.get("type")

            if message_type != "text":
                log.info("whatsapp_unsupported_message_type", message_type=message_type)
                return Response(status_code=200)

            message_text = message["text"]["body"]

            log.info(
                "whatsapp_message_received",
                sender=sender_phone,
                message_id=message_id,
                text_length=len(message_text),
            )

            background_tasks.add_task(
                _process_message,
                phone=sender_phone,
                message_id=message_id,
                text=message_text,
            )

        except (KeyError, IndexError, TypeError) as exc:
            log.error("whatsapp_payload_parse_error", error=str(exc))

        return Response(status_code=200)

    async def _process_message(phone: str, message_id: str, text: str) -> None:
        """Background task: mark read, run LangGraph agent, send reply."""
        try:
            await _meta.mark_as_read(message_id)

            # Phone number is the thread_id — gives each user persistent conversation history
            answer = await graph_run(question=text, thread_id=phone)

            if len(answer) > 4096:
                answer = answer[:4090] + "..."

            await _meta.send_text_message(to=phone, text=answer)

            log.info("whatsapp_reply_sent", phone=phone, answer_length=len(answer))

        except Exception as exc:
            log.error(
                "whatsapp_process_message_failed",
                phone=phone,
                message_id=message_id,
                error=str(exc),
            )
            try:
                await _meta.send_text_message(
                    to=phone,
                    text="Sorry, I encountered an error processing your message. Please try again.",
                )
            except Exception:
                pass

    return router
