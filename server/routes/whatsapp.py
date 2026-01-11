"""WhatsApp webhook routes for Donna AI.

This endpoint receives messages from n8n (which handles the Meta webhook)
and processes them through Donna.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from ..agents.donna import DonnaRuntime
from ..logging_config import logger


router = APIRouter(prefix="/whatsapp", tags=["whatsapp"])


class IncomingMessageRequest(BaseModel):
    """Request body for incoming WhatsApp message from n8n."""

    phone: str
    message: str
    profile_name: Optional[str] = None
    message_id: Optional[str] = None
    message_type: str = "text"
    is_audio: bool = False
    timestamp: Optional[str] = None


class MessageResponse(BaseModel):
    """Response for message processing."""

    ok: bool
    message: str = "Processing"


async def process_message_async(phone: str, message: str, profile_name: Optional[str]):
    """Process message asynchronously."""
    try:
        runtime = DonnaRuntime(phone)
        result = await runtime.execute(message, profile_name)
        logger.info(f"Message processed for {phone}: {result}")
    except Exception as e:
        logger.error(f"Failed to process message for {phone}: {e}")


@router.post("/webhook", response_model=MessageResponse)
async def receive_message(
    request: IncomingMessageRequest,
    background_tasks: BackgroundTasks
):
    """Receive incoming WhatsApp message from n8n.

    n8n workflow should call this endpoint with the parsed message data.
    We return immediately and process asynchronously for fast response.
    """
    logger.info(f"Received message from {request.phone}: {request.message[:50]}...")

    if not request.phone or not request.message:
        raise HTTPException(status_code=400, detail="Missing phone or message")

    # Process in background for fast response
    background_tasks.add_task(
        process_message_async,
        request.phone,
        request.message,
        request.profile_name
    )

    return MessageResponse(ok=True, message="Processing")


@router.post("/webhook/sync")
async def receive_message_sync(request: IncomingMessageRequest):
    """Synchronous version - waits for processing to complete.

    Use this for testing or when you need the response immediately.
    """
    logger.info(f"Received sync message from {request.phone}: {request.message[:50]}...")

    if not request.phone or not request.message:
        raise HTTPException(status_code=400, detail="Missing phone or message")

    try:
        runtime = DonnaRuntime(request.phone)
        result = await runtime.execute(request.message, request.profile_name)
        return {
            "ok": True,
            "result": result
        }
    except Exception as e:
        logger.error(f"Sync processing failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "service": "donna-whatsapp"}


__all__ = ["router"]
