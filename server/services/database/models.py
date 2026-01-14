"""Database models matching Nhost schema v2."""

from __future__ import annotations

from datetime import datetime, date
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from enum import Enum


# ============================================
# ENUMS
# ============================================

class TaskStatus(str, Enum):
    PENDING = "pending"
    REMINDED = "reminded"
    COMPLETED = "completed"
    DROPPED = "dropped"


class RecurringTaskStatus(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    DROPPED = "dropped"


class TaskFrequency(str, Enum):
    DAILY = "daily"
    WEEKLY = "weekly"
    CUSTOM = "custom"


class InteractionType(str, Enum):
    CREATED = "created"
    REMINDED = "reminded"
    CHECKIN = "checkin"
    RESPONSE = "response"
    COMPLETED = "completed"
    SNOOZED = "snoozed"
    SKIPPED = "skipped"
    DROPPED = "dropped"


class InteractionContext(str, Enum):
    MORNING_BRIEF = "morning_brief"
    EVENING_CHECKIN = "evening_checkin"
    RANDOM_CHECKIN = "random_checkin"
    DIRECT = "direct"
    SCHEDULED = "scheduled"
    WEBHOOK = "webhook"


class TriggerType(str, Enum):
    TASK_REMINDER = "task_reminder"
    TASK_CHECKIN = "task_checkin"
    RECURRING_REMINDER = "recurring_reminder"
    RECURRING_CHECKIN = "recurring_checkin"
    MORNING_BRIEF = "morning_brief"
    EVENING_CHECKIN = "evening_checkin"


class BriefType(str, Enum):
    MORNING = "morning"
    EVENING = "evening"
    WEEKLY = "weekly"


# ============================================
# USER MODEL
# ============================================

class UserPreferences(BaseModel):
    """User preferences stored as JSONB."""
    morning_brief_time: str = "08:00"
    evening_checkin_time: str = "18:00"
    quiet_hours_start: str = "23:00"
    quiet_hours_end: str = "07:00"


class UserPatterns(BaseModel):
    """Learned patterns stored as JSONB."""
    avg_task_completion_days: Optional[float] = None
    active_hours: Optional[List[int]] = None  # [9, 10, 11, 14, 15, 16]
    response_rate: Optional[float] = None  # 0-1
    preferred_reminder_time: Optional[str] = None


class User(BaseModel):
    """User profile model - matches users table."""

    id: Optional[str] = None
    phone: str
    name: Optional[str] = None
    timezone: str = "Asia/Kolkata"
    preferences: UserPreferences = Field(default_factory=UserPreferences)
    learned_patterns: UserPatterns = Field(default_factory=UserPatterns)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    # Legacy compatibility
    @property
    def phone_no(self) -> str:
        return self.phone

    @property
    def default_reminder_method(self) -> str:
        return "whatsapp"


# ============================================
# TASK MODEL (one-time tasks)
# ============================================

class TaskAccountability(BaseModel):
    """Accountability tracking stored as JSONB."""
    reminder_count: int = 0
    snooze_count: int = 0
    escalation_stage: int = 0  # 0-5
    last_interaction_at: Optional[datetime] = None


class Task(BaseModel):
    """One-time task model - matches tasks table."""

    id: Optional[str] = None
    user_phone: str
    title: str
    description: Optional[str] = None
    status: TaskStatus = TaskStatus.PENDING
    priority: int = 3  # 1=highest, 5=lowest

    # Timing
    created_at: Optional[datetime] = None
    remind_at: Optional[datetime] = None
    due_date: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    # Vector reference
    vector_id: Optional[str] = None

    # Accountability
    accountability: TaskAccountability = Field(default_factory=TaskAccountability)

    # Flexible metadata
    metadata: Dict[str, Any] = Field(default_factory=dict)

    updated_at: Optional[datetime] = None


# ============================================
# RECURRING TASK MODEL (habits, routines)
# ============================================

class RecurringSchedule(BaseModel):
    """Schedule for recurring tasks stored as JSONB."""
    times: List[str] = ["09:00"]  # ["09:00", "12:00", "16:00", "20:00"]
    days: List[int] = [1, 2, 3, 4, 5, 6, 7]  # 1=Mon, 7=Sun


class RecurringMetric(BaseModel):
    """Metric tracking for habits stored as JSONB."""
    type: str  # "count", "duration", "distance"
    unit: str  # "glasses", "steps", "pages", "minutes"
    target: Optional[int] = None  # 8 glasses, 10000 steps


class RecurringTask(BaseModel):
    """Recurring task/habit model - matches recurring_tasks table."""

    id: Optional[str] = None
    user_phone: str
    title: str
    description: Optional[str] = None
    status: RecurringTaskStatus = RecurringTaskStatus.ACTIVE

    # Frequency settings
    frequency: TaskFrequency = TaskFrequency.DAILY
    times_per_day: int = 1
    schedule: RecurringSchedule = Field(default_factory=RecurringSchedule)

    # Streaks
    streak_current: int = 0
    streak_best: int = 0

    # Optional metric tracking
    metric: Optional[RecurringMetric] = None

    # Vector reference
    vector_id: Optional[str] = None

    # Timing
    created_at: Optional[datetime] = None
    next_reminder_at: Optional[datetime] = None

    # Flexible metadata
    metadata: Dict[str, Any] = Field(default_factory=dict)

    updated_at: Optional[datetime] = None


# ============================================
# RECURRING TASK LOG MODEL
# ============================================

class MetricEntry(BaseModel):
    """Single metric entry."""
    time: str
    value: int


class RecurringTaskLog(BaseModel):
    """Daily log for recurring task - matches recurring_task_logs table."""

    id: Optional[str] = None
    recurring_task_id: str
    user_phone: str
    date: date

    scheduled_count: int = 0
    completed_count: int = 0
    skipped: bool = False

    metric_values: Optional[List[MetricEntry]] = None
    streak_maintained: Optional[bool] = None

    notes: Optional[str] = None
    created_at: Optional[datetime] = None


# ============================================
# TASK INTERACTION MODEL
# ============================================

class TaskInteraction(BaseModel):
    """Every touchpoint between Donna and user - matches task_interactions table."""

    id: Optional[str] = None
    user_phone: str

    # Link to task (one will be set)
    task_id: Optional[str] = None
    recurring_task_id: Optional[str] = None

    # Interaction details
    type: InteractionType
    donna_message: Optional[str] = None
    user_message: Optional[str] = None
    context: Optional[InteractionContext] = None

    # Vector reference
    vector_id: Optional[str] = None

    timestamp: Optional[datetime] = None


# ============================================
# CONVERSATION MODEL
# ============================================

class Conversation(BaseModel):
    """Chat message - matches conversations table."""

    id: Optional[str] = None
    user_phone: str
    direction: str  # "incoming" or "outgoing"
    message: str

    # Related task (optional)
    related_task_id: Optional[str] = None
    related_recurring_task_id: Optional[str] = None

    # Vector reference
    vector_id: Optional[str] = None

    metadata: Dict[str, Any] = Field(default_factory=dict)
    timestamp: Optional[datetime] = None


# ============================================
# BRIEF MODEL
# ============================================

class Brief(BaseModel):
    """Morning/evening brief - matches briefs table."""

    id: Optional[str] = None
    user_phone: str
    type: BriefType

    task_ids: List[str] = Field(default_factory=list)
    recurring_task_ids: List[str] = Field(default_factory=list)

    content_summary: Optional[str] = None
    user_engaged: bool = False
    response_time_seconds: Optional[int] = None

    sent_at: Optional[datetime] = None


# ============================================
# SCHEDULED TRIGGER MODEL
# ============================================

class ScheduledTrigger(BaseModel):
    """Webhook trigger queue - matches scheduled_triggers table."""

    id: Optional[str] = None
    user_phone: str

    trigger_type: TriggerType
    task_id: Optional[str] = None
    recurring_task_id: Optional[str] = None

    trigger_at: datetime
    status: str = "pending"  # pending, triggered, cancelled
    triggered_at: Optional[datetime] = None

    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[datetime] = None


# ============================================
# LEGACY MODELS (for backward compatibility)
# ============================================

class Schedule(BaseModel):
    """Legacy schedule/reminder model - matches schedule table in Nhost."""

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
    """Legacy chat history model - matches chats table in Nhost."""

    id: Optional[str] = None
    phone_no: str
    chat: str
    type: str  # "received" or "sent"
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class Trigger(BaseModel):
    """Legacy trigger model for scheduled actions."""

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
