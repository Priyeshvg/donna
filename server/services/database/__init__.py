"""Database abstraction layer for Donna AI.

Supports Nhost Postgres via GraphQL.
v2 schema includes tasks, recurring_tasks, and accountability tracking.
"""

from .client import DatabaseClient, get_database_client
from .client_v2 import get_database_client_v2, NhostClientV2
from .models import (
    # New models
    User, UserPreferences, UserPatterns,
    Task, TaskStatus, TaskAccountability,
    RecurringTask, RecurringTaskStatus, RecurringSchedule, RecurringMetric,
    RecurringTaskLog, MetricEntry,
    TaskInteraction, InteractionType, InteractionContext,
    Conversation,
    Brief, BriefType,
    ScheduledTrigger, TriggerType,
    # Legacy models
    Schedule, Chat, Trigger, VectorMemory,
)

__all__ = [
    # Clients
    "DatabaseClient",
    "get_database_client",
    "get_database_client_v2",
    "NhostClientV2",
    # New models
    "User", "UserPreferences", "UserPatterns",
    "Task", "TaskStatus", "TaskAccountability",
    "RecurringTask", "RecurringTaskStatus", "RecurringSchedule", "RecurringMetric",
    "RecurringTaskLog", "MetricEntry",
    "TaskInteraction", "InteractionType", "InteractionContext",
    "Conversation",
    "Brief", "BriefType",
    "ScheduledTrigger", "TriggerType",
    # Legacy models
    "Schedule", "Chat", "Trigger", "VectorMemory",
]
