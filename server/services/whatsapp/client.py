"""WhatsApp client for sending messages.

Supports two modes:
1. Direct Meta API (if WHATSAPP_ACCESS_TOKEN is set)
2. n8n relay (if N8N_SEND_WEBHOOK_URL is set) - recommended
"""

from __future__ import annotations

import os
from typing import List, Optional
from functools import lru_cache

import httpx

from ...logging_config import logger
from .models import OutgoingMessage, ImageMessage, TemplateMessage


class N8nWhatsAppClient:
    """WhatsApp client that sends via n8n webhook (recommended).

    This approach lets n8n manage the WhatsApp token, avoiding token
    expiration issues and keeping credentials in one place.
    """

    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url
        self._client = httpx.AsyncClient(timeout=30.0)

    async def send_text(self, to: str, text: str) -> bool:
        """Send a text message via n8n."""
        try:
            response = await self._client.post(
                self.webhook_url,
                json={
                    "phone": to,
                    "type": "text",
                    "message": text,
                },
            )
            response.raise_for_status()
            logger.info(f"WhatsApp message sent via n8n to {to}")
            return True
        except httpx.HTTPStatusError as e:
            logger.error(f"n8n webhook failed: {e}")
            if hasattr(e, 'response'):
                logger.error(f"Response: {e.response.text}")
            return False
        except Exception as e:
            logger.error(f"Failed to send via n8n: {e}")
            return False

    async def send_image(self, to: str, image_url: str, caption: str = "") -> bool:
        """Send an image message via n8n."""
        try:
            response = await self._client.post(
                self.webhook_url,
                json={
                    "phone": to,
                    "type": "image",
                    "image_url": image_url,
                    "caption": caption,
                },
            )
            response.raise_for_status()
            logger.info(f"WhatsApp image sent via n8n to {to}")
            return True
        except Exception as e:
            logger.error(f"Failed to send image via n8n: {e}")
            return False


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
            payload = message.to_meta_payload()
            response = await self._client.post(
                self.base_url,
                json=payload,
                headers={
                    "Authorization": f"Bearer {self.access_token}",
                    "Content-Type": "application/json",
                },
            )
            response.raise_for_status()
            logger.info(f"WhatsApp message sent to {message.to}")
            return True
        except httpx.HTTPStatusError as e:
            logger.error(f"Failed to send WhatsApp message: {e}")
            logger.error(f"Response: {e.response.text}")
            return False
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


# Singleton instance - can be either N8nWhatsAppClient or WhatsAppClient
_whatsapp_client = None


def get_whatsapp_client():
    """Get the singleton WhatsApp client.

    Priority:
    1. n8n webhook (N8N_SEND_WEBHOOK_URL) - recommended, token managed by n8n
    2. Direct Meta API (WHATSAPP_ACCESS_TOKEN) - fallback
    3. None if neither configured

    Returns:
        N8nWhatsAppClient, WhatsAppClient, or None
    """
    global _whatsapp_client
    if _whatsapp_client is None:
        # Option 1: n8n webhook (recommended)
        n8n_webhook = os.getenv("N8N_SEND_WEBHOOK_URL")
        if n8n_webhook:
            logger.info(f"Using n8n for WhatsApp sending: {n8n_webhook}")
            _whatsapp_client = N8nWhatsAppClient(n8n_webhook)
            return _whatsapp_client

        # Option 2: Direct Meta API
        phone_number_id = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
        access_token = os.getenv("WHATSAPP_ACCESS_TOKEN")

        if phone_number_id and access_token:
            logger.info("Using direct Meta API for WhatsApp")
            _whatsapp_client = WhatsAppClient(phone_number_id, access_token)
            return _whatsapp_client

        # Option 3: Not configured
        logger.warning("WhatsApp not configured - messages won't be sent")
        return None

    return _whatsapp_client


__all__ = ["WhatsAppClient", "N8nWhatsAppClient", "get_whatsapp_client"]
