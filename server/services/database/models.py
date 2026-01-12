"""Database models matching Nhost schema from n8n workflow."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class User(BaseModel):
    """User profile model - matches user_phone_no table in Nhost."""

    id: Optional[str] = None
    phone_no: str
    name: Optional[str] = None
    email: Optional[str] = None
    user_context: Optional[str] = None
    default_reminder_method: str = "whatsapp"
    timezone: str = "Asia/Kolkata"
    # Onboarding tracks usage counts - no intro logic, just feature usage
    onboarding: Optional[Dict[str, Any]] = Field(default_factory=lambda: {
        "reminder_count": 0,
        "memory_count": 0,
        "message_count": 0,
    })
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class Schedule(BaseModel):
    """Schedule/reminder model - matches schedule table in Nhost."""

    id: Optional[str] = None
    user_id: str = "00000000-0000-0000-0000-000000000001"
    phone_number: str
    call_time: Optional[datetime] = None
    context: str
    call_status: str = "pending"
    task_status: str = "pending"
    habit_type: Optional[str] = None
    importance: str = "medium"
    reminder_method: str = "whatsapp"
    rich_context: Optional[Dict[str, Any]] = None
    follow_up_time: Optional[datetime] = None
    follow_up_count: int = 0
    reminder_sent: bool = False
    is_recurring: bool = False
    recurrence_rule: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class Chat(BaseModel):
    """Chat history model - matches chats table in Nhost."""

    id: Optional[str] = None
    phone_no: str
    chat: str
    type: str  # "received" or "sent"
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class Trigger(BaseModel):
    """Trigger model for scheduled actions (reminders, follow-ups)."""

    id: Optional[int] = None
    agent_name: str
    phone_number: str
    payload: str
    start_time: Optional[str] = None
    next_trigger: Optional[str] = None
    recurrence_rule: Optional[str] = None
    timezone: str = "Asia/Kolkata"
    status: str = "active"
    last_error: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class VectorMemory(BaseModel):
    """Vector memory entry for Pinecone."""

    id: Optional[str] = None
    phone_number: str
    content: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
    embedding: Optional[List[float]] = None
