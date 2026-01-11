"""WhatsApp integration for Donna AI.

Handles incoming messages from n8n webhook and sends responses via Meta API.
"""

from .client import WhatsAppClient, get_whatsapp_client
from .models import IncomingMessage, OutgoingMessage, ImageMessage, TemplateMessage

__all__ = [
    "WhatsAppClient",
    "get_whatsapp_client",
    "IncomingMessage",
    "OutgoingMessage",
    "ImageMessage",
    "TemplateMessage",
]
