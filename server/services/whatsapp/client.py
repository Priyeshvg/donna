"""WhatsApp client for sending messages via Meta Cloud API."""

from __future__ import annotations

import os
from typing import List, Optional
from functools import lru_cache

import httpx

from ...logging_config import logger
from .models import OutgoingMessage, ImageMessage, TemplateMessage


class WhatsAppClient:
    """Client for sending WhatsApp messages via Meta Cloud API."""

    def __init__(
        self,
        phone_number_id: str,
        access_token: str,
        api_version: str = "v21.0"
    ):
        self.phone_number_id = phone_number_id
        self.access_token = access_token
        self.api_version = api_version
        self.base_url = f"https://graph.facebook.com/{api_version}/{phone_number_id}/messages"
        self._client = httpx.AsyncClient(timeout=30.0)

    async def send_message(self, message: OutgoingMessage) -> bool:
        """Send a text message."""
        try:
            response = await self._client.post(
                self.base_url,
                json=message.to_meta_payload(),
                headers={
                    "Authorization": f"Bearer {self.access_token}",
                    "Content-Type": "application/json",
                },
            )
            response.raise_for_status()
            logger.info(f"WhatsApp message sent to {message.to}")
            return True
        except Exception as e:
            logger.error(f"Failed to send WhatsApp message: {e}")
            return False

    async def send_messages(self, messages: List[OutgoingMessage]) -> List[bool]:
        """Send multiple messages in sequence."""
        results = []
        for msg in messages:
            result = await self.send_message(msg)
            results.append(result)
        return results

    async def send_image(self, message: ImageMessage) -> bool:
        """Send an image message."""
        try:
            response = await self._client.post(
                self.base_url,
                json=message.to_meta_payload(),
                headers={
                    "Authorization": f"Bearer {self.access_token}",
                    "Content-Type": "application/json",
                },
            )
            response.raise_for_status()
            logger.info(f"WhatsApp image sent to {message.to}")
            return True
        except Exception as e:
            logger.error(f"Failed to send WhatsApp image: {e}")
            return False

    async def send_template(self, message: TemplateMessage) -> bool:
        """Send a template message (for messaging others on user's behalf)."""
        try:
            response = await self._client.post(
                self.base_url,
                json=message.to_meta_payload(),
                headers={
                    "Authorization": f"Bearer {self.access_token}",
                    "Content-Type": "application/json",
                },
            )
            response.raise_for_status()
            logger.info(f"WhatsApp template sent to {message.to}")
            return True
        except Exception as e:
            logger.error(f"Failed to send WhatsApp template: {e}")
            return False

    async def send_text(self, to: str, text: str) -> bool:
        """Convenience method to send a simple text message."""
        return await self.send_message(OutgoingMessage(to=to, message=text))


# Singleton instance
_whatsapp_client: Optional[WhatsAppClient] = None


def get_whatsapp_client() -> Optional[WhatsAppClient]:
    """Get the singleton WhatsApp client. Returns None if not configured."""
    global _whatsapp_client
    if _whatsapp_client is None:
        phone_number_id = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
        access_token = os.getenv("WHATSAPP_ACCESS_TOKEN")

        if not phone_number_id or not access_token:
            # WhatsApp not configured - n8n handles sending
            logger.info("WhatsApp client not configured - n8n will handle message sending")
            return None

        _whatsapp_client = WhatsAppClient(phone_number_id, access_token)

    return _whatsapp_client


__all__ = ["WhatsAppClient", "get_whatsapp_client"]
