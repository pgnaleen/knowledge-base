"""Meta WhatsApp Cloud API — send messages and mark as read."""

import os
import httpx
from logging_config import get_logger

log = get_logger(__name__)
GRAPH_BASE = "https://graph.facebook.com/v20.0"


class MetaApiClient:
    """Async client for Meta WhatsApp Cloud API."""

    def __init__(self) -> None:
        self._token = os.environ["WHATSAPP_TOKEN"]
        self._phone_id = os.environ["WHATSAPP_PHONE_NUMBER_ID"]
        self._headers = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }

    async def send_text_message(self, to: str, text: str) -> None:
        """Send a text message to a WhatsApp number.

        Args:
            to: Recipient phone number in E.164 format (e.g. "6591234567")
            text: Message body text
        """
        url = f"{GRAPH_BASE}/{self._phone_id}/messages"
        payload = {"messaging_product": "whatsapp", "to": to, "text": {"body": text}}
        async with httpx.AsyncClient(timeout=30) as http:
            resp = await http.post(url, json=payload, headers=self._headers)
            if resp.status_code >= 400:
                log.error("whatsapp_send_failed", to=to, status=resp.status_code)
            else:
                log.info("whatsapp_message_sent", to=to)

    async def mark_as_read(self, message_id: str) -> None:
        """Mark a received message as read (shows double blue ticks).

        Args:
            message_id: The wamid of the message to mark read
        """
        url = f"{GRAPH_BASE}/{self._phone_id}/messages"
        payload = {"messaging_product": "whatsapp", "status": "read", "message_id": message_id}
        async with httpx.AsyncClient(timeout=10) as http:
            resp = await http.post(url, json=payload, headers=self._headers)
            if resp.status_code >= 400:
                log.warning("whatsapp_mark_read_failed", message_id=message_id)
