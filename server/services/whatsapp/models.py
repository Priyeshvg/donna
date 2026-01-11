"""WhatsApp message models."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field


class IncomingMessage(BaseModel):
    """Incoming WhatsApp message from n8n webhook."""

    phone: str
    message: str
    profile_name: Optional[str] = None
    message_id: Optional[str] = None
    message_type: str = "text"
    is_audio: bool = False
    audio_id: Optional[str] = None
    timestamp: Optional[datetime] = None

    @classmethod
    def from_n8n_payload(cls, payload: Dict[str, Any]) -> "IncomingMessage":
        """Parse incoming message from n8n webhook format."""
        return cls(
            phone=payload.get("phone", ""),
            message=payload.get("message", ""),
            profile_name=payload.get("profileName"),
            message_id=payload.get("messageId"),
            message_type=payload.get("messageType", "text"),
            is_audio=payload.get("isAudio", False),
            audio_id=payload.get("audioId"),
            timestamp=datetime.fromisoformat(payload["timestamp"]) if payload.get("timestamp") else None,
        )


class OutgoingMessage(BaseModel):
    """Outgoing WhatsApp message to send via Meta API."""

    to: str
    message: str
    message_type: str = "text"

    def to_meta_payload(self) -> Dict[str, Any]:
        """Convert to Meta WhatsApp API format."""
        return {
            "messaging_product": "whatsapp",
            "to": self.to,
            "type": "text",
            "text": {
                "body": self.message
            }
        }


class ImageMessage(BaseModel):
    """WhatsApp image message."""

    to: str
    image_url: str
    caption: Optional[str] = None

    def to_meta_payload(self) -> Dict[str, Any]:
        """Convert to Meta WhatsApp API format."""
        payload = {
            "messaging_product": "whatsapp",
            "to": self.to,
            "type": "image",
            "image": {
                "link": self.image_url
            }
        }
        if self.caption:
            payload["image"]["caption"] = self.caption
        return payload


class TemplateMessage(BaseModel):
    """WhatsApp template message for messaging others."""

    to: str
    template_name: str
    message: str
    sender_name: str
    language_code: str = "en"

    def to_meta_payload(self) -> Dict[str, Any]:
        """Convert to Meta WhatsApp API format for template messages."""
        return {
            "messaging_product": "whatsapp",
            "to": self.to,
            "type": "template",
            "template": {
                "name": self.template_name,
                "language": {
                    "code": self.language_code
                },
                "components": [
                    {
                        "type": "body",
                        "parameters": [
                            {"type": "text", "text": self.message},
                            {"type": "text", "text": self.sender_name}
                        ]
                    }
                ]
            }
        }
