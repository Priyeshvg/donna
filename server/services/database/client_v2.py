"""Database client v2 for new schema (tasks, recurring_tasks, etc.)."""

from __future__ import annotations

import os
from datetime import datetime, date
from typing import Any, Dict, List, Optional

import httpx

from ...logging_config import logger
from .models import (
    User, UserPreferences, UserPatterns,
    Task, TaskStatus, TaskAccountability,
    RecurringTask, RecurringTaskStatus, RecurringSchedule, RecurringMetric,
    RecurringTaskLog,
    TaskInteraction, InteractionType, InteractionContext,
    Conversation,
    Brief, BriefType,
    ScheduledTrigger, TriggerType,
    # Legacy
    Chat, Schedule,
)


class NhostClientV2:
    """Nhost GraphQL client for v2 schema."""

    MAX_RETRIES = 2
    RETRY_DELAY = 0.5

    def __init__(self, endpoint: str, admin_secret: str):
        self.endpoint = endpoint
        self.headers = {
            "Content-Type": "application/json",
            "x-hasura-admin-secret": admin_secret,
        }
        self._client = httpx.AsyncClient(timeout=30.0)

    async def _execute(self, query: str, variables: Dict[str, Any] = None) -> Dict[str, Any]:
        """Execute a GraphQL query with retry logic."""
        import asyncio

        payload = {"query": query}
        if variables:
            payload["variables"] = variables

        last_error = None
        for attempt in range(self.MAX_RETRIES + 1):
            try:
                response = await self._client.post(
                    self.endpoint,
                    json=payload,
                    headers=self.headers,
                )
                response.raise_for_status()
                result = response.json()

                if "errors" in result:
                    logger.error(f"GraphQL errors: {result['errors']}")
                    raise Exception(f"GraphQL error: {result['errors']}")

                return result.get("data", {})
            except (httpx.TimeoutException, httpx.HTTPStatusError) as e:
                last_error = e
                if attempt < self.MAX_RETRIES:
                    logger.warning(f"Nhost query failed (attempt {attempt + 1}), retrying: {e}")
                    await asyncio.sleep(self.RETRY_DELAY * (attempt + 1))
                else:
                    logger.error(f"Nhost query failed after {self.MAX_RETRIES + 1} attempts: {e}")
                    raise
            except Exception as e:
                logger.error(f"Nhost query failed: {e}")
                raise

        raise last_error

    # ============================================
    # USER OPERATIONS (new schema)
    # ============================================

    async def get_user(self, phone: str) -> Optional[User]:
        """Get user by phone number."""
        query = """
        query GetUser($phone: String!) {
            donna_users(where: {phone: {_eq: $phone}}, limit: 1) {
                id phone name timezone preferences learned_patterns created_at updated_at
            }
        }
        """
        data = await self._execute(query, {"phone": phone})
        users = data.get("donna_users", [])
        if users:
            u = users[0]
            return User(
                id=u.get("id"),
                phone=u.get("phone"),
                name=u.get("name"),
                timezone=u.get("timezone", "Asia/Kolkata"),
                preferences=UserPreferences(**(u.get("preferences") or {})),
                learned_patterns=UserPatterns(**(u.get("learned_patterns") or {})),
                created_at=u.get("created_at"),
                updated_at=u.get("updated_at"),
            )
        return None

    async def create_user(self, user: User) -> User:
        """Create a new user."""
        query = """
        mutation CreateUser($object: donna_users_insert_input!) {
            insert_donna_users_one(object: $object) {
                id phone name timezone preferences learned_patterns created_at updated_at
            }
        }
        """
        obj = {
            "phone": user.phone,
            "name": user.name,
            "timezone": user.timezone,
            "preferences": user.preferences.model_dump() if user.preferences else {},
            "learned_patterns": user.learned_patterns.model_dump() if user.learned_patterns else {},
        }
        data = await self._execute(query, {"object": obj})
        u = data["insert_donna_users_one"]
        return User(
            id=u.get("id"),
            phone=u.get("phone"),
            name=u.get("name"),
            timezone=u.get("timezone"),
            preferences=UserPreferences(**(u.get("preferences") or {})),
            learned_patterns=UserPatterns(**(u.get("learned_patterns") or {})),
            created_at=u.get("created_at"),
            updated_at=u.get("updated_at"),
        )

    async def update_user(self, phone: str, updates: Dict[str, Any]) -> Optional[User]:
        """Update user fields."""
        query = """
        mutation UpdateUser($phone: String!, $set: donna_users_set_input!) {
            update_donna_users(where: {phone: {_eq: $phone}}, _set: $set) {
                returning {
                    id phone name timezone preferences learned_patterns created_at updated_at
                }
            }
        }
        """
        data = await self._execute(query, {"phone": phone, "set": updates})
        returning = data.get("update_donna_users", {}).get("returning", [])
        if returning:
            u = returning[0]
            return User(
                id=u.get("id"),
                phone=u.get("phone"),
                name=u.get("name"),
                timezone=u.get("timezone"),
                preferences=UserPreferences(**(u.get("preferences") or {})),
                learned_patterns=UserPatterns(**(u.get("learned_patterns") or {})),
                created_at=u.get("created_at"),
                updated_at=u.get("updated_at"),
            )
        return None

    # ============================================
    # TASK OPERATIONS (one-time tasks)
    # ============================================

    async def create_task(self, task: Task) -> Task:
        """Create a new task."""
        query = """
        mutation CreateTask($object: tasks_insert_input!) {
            insert_tasks_one(object: $object) {
                id user_phone title description status priority
                created_at remind_at due_date completed_at
                vector_id accountability metadata updated_at
            }
        }
        """
        obj = {
            "user_phone": task.user_phone,
            "title": task.title,
            "description": task.description,
            "status": task.status.value if isinstance(task.status, TaskStatus) else task.status,
            "priority": task.priority,
            "remind_at": task.remind_at.isoformat() if task.remind_at else None,
            "due_date": task.due_date.isoformat() if task.due_date else None,
            "vector_id": task.vector_id,
            "accountability": task.accountability.model_dump() if task.accountability else {},
            "metadata": task.metadata or {},
        }
        obj = {k: v for k, v in obj.items() if v is not None}
        data = await self._execute(query, {"object": obj})
        return self._parse_task(data["insert_tasks_one"])

    async def get_task(self, task_id: str) -> Optional[Task]:
        """Get task by ID."""
        query = """
        query GetTask($id: uuid!) {
            tasks_by_pk(id: $id) {
                id user_phone title description status priority
                created_at remind_at due_date completed_at
                vector_id accountability metadata updated_at
            }
        }
        """
        data = await self._execute(query, {"id": task_id})
        t = data.get("tasks_by_pk")
        if t:
            return self._parse_task(t)
        return None

    async def get_tasks(
        self,
        phone: str,
        status: Optional[TaskStatus] = None,
        limit: int = 50
    ) -> List[Task]:
        """Get tasks for a user."""
        where = {"user_phone": {"_eq": phone}}
        if status:
            where["status"] = {"_eq": status.value}

        query = """
        query GetTasks($where: tasks_bool_exp!, $limit: Int!) {
            tasks(where: $where, order_by: {remind_at: asc_nulls_last}, limit: $limit) {
                id user_phone title description status priority
                created_at remind_at due_date completed_at
                vector_id accountability metadata updated_at
            }
        }
        """
        data = await self._execute(query, {"where": where, "limit": limit})
        return [self._parse_task(t) for t in data.get("tasks", [])]

    async def get_pending_tasks(self, phone: str) -> List[Task]:
        """Get pending tasks for a user."""
        return await self.get_tasks(phone, status=TaskStatus.PENDING)

    async def update_task(self, task_id: str, updates: Dict[str, Any]) -> Optional[Task]:
        """Update task fields."""
        query = """
        mutation UpdateTask($id: uuid!, $set: tasks_set_input!) {
            update_tasks_by_pk(pk_columns: {id: $id}, _set: $set) {
                id user_phone title description status priority
                created_at remind_at due_date completed_at
                vector_id accountability metadata updated_at
            }
        }
        """
        data = await self._execute(query, {"id": task_id, "set": updates})
        t = data.get("update_tasks_by_pk")
        if t:
            return self._parse_task(t)
        return None

    async def complete_task(self, task_id: str) -> Optional[Task]:
        """Mark task as completed."""
        return await self.update_task(task_id, {
            "status": "completed",
            "completed_at": datetime.utcnow().isoformat(),
        })

    async def drop_task(self, task_id: str) -> Optional[Task]:
        """Mark task as dropped."""
        return await self.update_task(task_id, {"status": "dropped"})

    async def get_due_tasks(self, before: datetime) -> List[Task]:
        """Get tasks due before given time."""
        query = """
        query GetDueTasks($before: timestamptz!) {
            tasks(
                where: {
                    remind_at: {_lte: $before},
                    status: {_eq: "pending"}
                },
                order_by: {remind_at: asc}
            ) {
                id user_phone title description status priority
                created_at remind_at due_date completed_at
                vector_id accountability metadata updated_at
            }
        }
        """
        data = await self._execute(query, {"before": before.isoformat()})
        return [self._parse_task(t) for t in data.get("tasks", [])]

    def _parse_task(self, t: Dict[str, Any]) -> Task:
        """Parse task from GraphQL response."""
        return Task(
            id=t.get("id"),
            user_phone=t.get("user_phone"),
            title=t.get("title"),
            description=t.get("description"),
            status=TaskStatus(t.get("status", "pending")),
            priority=t.get("priority", 3),
            created_at=t.get("created_at"),
            remind_at=t.get("remind_at"),
            due_date=t.get("due_date"),
            completed_at=t.get("completed_at"),
            vector_id=t.get("vector_id"),
            accountability=TaskAccountability(**(t.get("accountability") or {})),
            metadata=t.get("metadata") or {},
            updated_at=t.get("updated_at"),
        )

    # ============================================
    # RECURRING TASK OPERATIONS
    # ============================================

    async def create_recurring_task(self, task: RecurringTask) -> RecurringTask:
        """Create a new recurring task."""
        query = """
        mutation CreateRecurringTask($object: recurring_tasks_insert_input!) {
            insert_recurring_tasks_one(object: $object) {
                id user_phone title description status frequency times_per_day schedule
                streak_current streak_best metric vector_id created_at next_reminder_at metadata updated_at
            }
        }
        """
        obj = {
            "user_phone": task.user_phone,
            "title": task.title,
            "description": task.description,
            "status": task.status.value if isinstance(task.status, RecurringTaskStatus) else task.status,
            "frequency": task.frequency.value if isinstance(task.frequency, str) else task.frequency,
            "times_per_day": task.times_per_day,
            "schedule": task.schedule.model_dump() if task.schedule else {},
            "streak_current": task.streak_current,
            "streak_best": task.streak_best,
            "metric": task.metric.model_dump() if task.metric else None,
            "vector_id": task.vector_id,
            "next_reminder_at": task.next_reminder_at.isoformat() if task.next_reminder_at else None,
            "metadata": task.metadata or {},
        }
        obj = {k: v for k, v in obj.items() if v is not None}
        data = await self._execute(query, {"object": obj})
        return self._parse_recurring_task(data["insert_recurring_tasks_one"])

    async def get_recurring_task(self, task_id: str) -> Optional[RecurringTask]:
        """Get recurring task by ID."""
        query = """
        query GetRecurringTask($id: uuid!) {
            recurring_tasks_by_pk(id: $id) {
                id user_phone title description status frequency times_per_day schedule
                streak_current streak_best metric vector_id created_at next_reminder_at metadata updated_at
            }
        }
        """
        data = await self._execute(query, {"id": task_id})
        t = data.get("recurring_tasks_by_pk")
        if t:
            return self._parse_recurring_task(t)
        return None

    async def get_recurring_tasks(
        self,
        phone: str,
        status: Optional[RecurringTaskStatus] = None
    ) -> List[RecurringTask]:
        """Get recurring tasks for a user."""
        where = {"user_phone": {"_eq": phone}}
        if status:
            where["status"] = {"_eq": status.value}

        query = """
        query GetRecurringTasks($where: recurring_tasks_bool_exp!) {
            recurring_tasks(where: $where, order_by: {created_at: desc}) {
                id user_phone title description status frequency times_per_day schedule
                streak_current streak_best metric vector_id created_at next_reminder_at metadata updated_at
            }
        }
        """
        data = await self._execute(query, {"where": where})
        return [self._parse_recurring_task(t) for t in data.get("recurring_tasks", [])]

    async def get_active_recurring_tasks(self, phone: str) -> List[RecurringTask]:
        """Get active recurring tasks for a user."""
        return await self.get_recurring_tasks(phone, status=RecurringTaskStatus.ACTIVE)

    async def update_recurring_task(self, task_id: str, updates: Dict[str, Any]) -> Optional[RecurringTask]:
        """Update recurring task fields."""
        query = """
        mutation UpdateRecurringTask($id: uuid!, $set: recurring_tasks_set_input!) {
            update_recurring_tasks_by_pk(pk_columns: {id: $id}, _set: $set) {
                id user_phone title description status frequency times_per_day schedule
                streak_current streak_best metric vector_id created_at next_reminder_at metadata updated_at
            }
        }
        """
        data = await self._execute(query, {"id": task_id, "set": updates})
        t = data.get("update_recurring_tasks_by_pk")
        if t:
            return self._parse_recurring_task(t)
        return None

    async def update_streak(self, task_id: str, increment: bool = True) -> Optional[RecurringTask]:
        """Update streak for recurring task."""
        task = await self.get_recurring_task(task_id)
        if not task:
            return None

        if increment:
            new_current = task.streak_current + 1
            new_best = max(task.streak_best, new_current)
        else:
            new_current = 0
            new_best = task.streak_best

        return await self.update_recurring_task(task_id, {
            "streak_current": new_current,
            "streak_best": new_best,
        })

    def _parse_recurring_task(self, t: Dict[str, Any]) -> RecurringTask:
        """Parse recurring task from GraphQL response."""
        metric = None
        if t.get("metric"):
            metric = RecurringMetric(**t["metric"])

        return RecurringTask(
            id=t.get("id"),
            user_phone=t.get("user_phone"),
            title=t.get("title"),
            description=t.get("description"),
            status=RecurringTaskStatus(t.get("status", "active")),
            frequency=t.get("frequency", "daily"),
            times_per_day=t.get("times_per_day", 1),
            schedule=RecurringSchedule(**(t.get("schedule") or {})),
            streak_current=t.get("streak_current", 0),
            streak_best=t.get("streak_best", 0),
            metric=metric,
            vector_id=t.get("vector_id"),
            created_at=t.get("created_at"),
            next_reminder_at=t.get("next_reminder_at"),
            metadata=t.get("metadata") or {},
            updated_at=t.get("updated_at"),
        )

    # ============================================
    # RECURRING TASK LOG OPERATIONS
    # ============================================

    async def log_recurring_task(self, log: RecurringTaskLog) -> RecurringTaskLog:
        """Log a recurring task completion."""
        query = """
        mutation LogRecurringTask($object: recurring_task_logs_insert_input!) {
            insert_recurring_task_logs_one(
                object: $object,
                on_conflict: {
                    constraint: idx_recurring_logs_unique,
                    update_columns: [completed_count, metric_values, streak_maintained, notes]
                }
            ) {
                id recurring_task_id user_phone date scheduled_count completed_count
                skipped metric_values streak_maintained notes created_at
            }
        }
        """
        obj = {
            "recurring_task_id": log.recurring_task_id,
            "user_phone": log.user_phone,
            "date": log.date.isoformat() if isinstance(log.date, date) else log.date,
            "scheduled_count": log.scheduled_count,
            "completed_count": log.completed_count,
            "skipped": log.skipped,
            "metric_values": [m.model_dump() for m in log.metric_values] if log.metric_values else None,
            "streak_maintained": log.streak_maintained,
            "notes": log.notes,
        }
        obj = {k: v for k, v in obj.items() if v is not None}
        data = await self._execute(query, {"object": obj})
        return self._parse_recurring_log(data["insert_recurring_task_logs_one"])

    async def get_recurring_task_logs(
        self,
        task_id: str,
        limit: int = 30
    ) -> List[RecurringTaskLog]:
        """Get logs for a recurring task."""
        query = """
        query GetRecurringTaskLogs($task_id: uuid!, $limit: Int!) {
            recurring_task_logs(
                where: {recurring_task_id: {_eq: $task_id}},
                order_by: {date: desc},
                limit: $limit
            ) {
                id recurring_task_id user_phone date scheduled_count completed_count
                skipped metric_values streak_maintained notes created_at
            }
        }
        """
        data = await self._execute(query, {"task_id": task_id, "limit": limit})
        return [self._parse_recurring_log(l) for l in data.get("recurring_task_logs", [])]

    def _parse_recurring_log(self, l: Dict[str, Any]) -> RecurringTaskLog:
        """Parse recurring task log from GraphQL response."""
        return RecurringTaskLog(
            id=l.get("id"),
            recurring_task_id=l.get("recurring_task_id"),
            user_phone=l.get("user_phone"),
            date=l.get("date"),
            scheduled_count=l.get("scheduled_count", 0),
            completed_count=l.get("completed_count", 0),
            skipped=l.get("skipped", False),
            metric_values=l.get("metric_values"),
            streak_maintained=l.get("streak_maintained"),
            notes=l.get("notes"),
            created_at=l.get("created_at"),
        )

    # ============================================
    # TASK INTERACTION OPERATIONS
    # ============================================

    async def log_interaction(self, interaction: TaskInteraction) -> TaskInteraction:
        """Log a task interaction."""
        query = """
        mutation LogInteraction($object: task_interactions_insert_input!) {
            insert_task_interactions_one(object: $object) {
                id user_phone task_id recurring_task_id type
                donna_message user_message context vector_id timestamp
            }
        }
        """
        obj = {
            "user_phone": interaction.user_phone,
            "task_id": interaction.task_id,
            "recurring_task_id": interaction.recurring_task_id,
            "type": interaction.type.value if isinstance(interaction.type, InteractionType) else interaction.type,
            "donna_message": interaction.donna_message,
            "user_message": interaction.user_message,
            "context": interaction.context.value if isinstance(interaction.context, InteractionContext) else interaction.context,
            "vector_id": interaction.vector_id,
        }
        obj = {k: v for k, v in obj.items() if v is not None}
        data = await self._execute(query, {"object": obj})
        return self._parse_interaction(data["insert_task_interactions_one"])

    async def get_interactions(
        self,
        phone: str,
        task_id: Optional[str] = None,
        recurring_task_id: Optional[str] = None,
        limit: int = 50
    ) -> List[TaskInteraction]:
        """Get interactions for a user or task."""
        where = {"user_phone": {"_eq": phone}}
        if task_id:
            where["task_id"] = {"_eq": task_id}
        if recurring_task_id:
            where["recurring_task_id"] = {"_eq": recurring_task_id}

        query = """
        query GetInteractions($where: task_interactions_bool_exp!, $limit: Int!) {
            task_interactions(where: $where, order_by: {timestamp: desc}, limit: $limit) {
                id user_phone task_id recurring_task_id type
                donna_message user_message context vector_id timestamp
            }
        }
        """
        data = await self._execute(query, {"where": where, "limit": limit})
        return [self._parse_interaction(i) for i in data.get("task_interactions", [])]

    async def get_recent_interactions(self, phone: str, hours: int = 24) -> List[TaskInteraction]:
        """Get interactions in the last N hours."""
        cutoff = datetime.utcnow().replace(microsecond=0)
        cutoff = cutoff.replace(hour=cutoff.hour - hours if cutoff.hour >= hours else 0)

        query = """
        query GetRecentInteractions($phone: String!, $since: timestamptz!) {
            task_interactions(
                where: {
                    user_phone: {_eq: $phone},
                    timestamp: {_gte: $since}
                },
                order_by: {timestamp: desc}
            ) {
                id user_phone task_id recurring_task_id type
                donna_message user_message context vector_id timestamp
            }
        }
        """
        data = await self._execute(query, {"phone": phone, "since": cutoff.isoformat()})
        return [self._parse_interaction(i) for i in data.get("task_interactions", [])]

    def _parse_interaction(self, i: Dict[str, Any]) -> TaskInteraction:
        """Parse interaction from GraphQL response."""
        return TaskInteraction(
            id=i.get("id"),
            user_phone=i.get("user_phone"),
            task_id=i.get("task_id"),
            recurring_task_id=i.get("recurring_task_id"),
            type=InteractionType(i.get("type")) if i.get("type") else None,
            donna_message=i.get("donna_message"),
            user_message=i.get("user_message"),
            context=InteractionContext(i.get("context")) if i.get("context") else None,
            vector_id=i.get("vector_id"),
            timestamp=i.get("timestamp"),
        )

    # ============================================
    # CONVERSATION OPERATIONS
    # ============================================

    async def save_conversation(self, conv: Conversation) -> Conversation:
        """Save a conversation message."""
        query = """
        mutation SaveConversation($object: conversations_insert_input!) {
            insert_conversations_one(object: $object) {
                id user_phone direction message related_task_id
                related_recurring_task_id vector_id metadata timestamp
            }
        }
        """
        obj = {
            "user_phone": conv.user_phone,
            "direction": conv.direction,
            "message": conv.message,
            "related_task_id": conv.related_task_id,
            "related_recurring_task_id": conv.related_recurring_task_id,
            "vector_id": conv.vector_id,
            "metadata": conv.metadata or {},
        }
        obj = {k: v for k, v in obj.items() if v is not None}
        data = await self._execute(query, {"object": obj})
        c = data["insert_conversations_one"]
        return Conversation(**c)

    async def get_conversations(self, phone: str, limit: int = 50) -> List[Conversation]:
        """Get recent conversations for a user."""
        query = """
        query GetConversations($phone: String!, $limit: Int!) {
            conversations(
                where: {user_phone: {_eq: $phone}},
                order_by: {timestamp: desc},
                limit: $limit
            ) {
                id user_phone direction message related_task_id
                related_recurring_task_id vector_id metadata timestamp
            }
        }
        """
        data = await self._execute(query, {"phone": phone, "limit": limit})
        return [Conversation(**c) for c in reversed(data.get("conversations", []))]

    # ============================================
    # BRIEF OPERATIONS
    # ============================================

    async def save_brief(self, brief: Brief) -> Brief:
        """Save a brief record."""
        query = """
        mutation SaveBrief($object: briefs_insert_input!) {
            insert_briefs_one(object: $object) {
                id user_phone type task_ids recurring_task_ids
                content_summary user_engaged response_time_seconds sent_at
            }
        }
        """
        obj = {
            "user_phone": brief.user_phone,
            "type": brief.type.value if isinstance(brief.type, BriefType) else brief.type,
            "task_ids": brief.task_ids,
            "recurring_task_ids": brief.recurring_task_ids,
            "content_summary": brief.content_summary,
            "user_engaged": brief.user_engaged,
            "response_time_seconds": brief.response_time_seconds,
        }
        obj = {k: v for k, v in obj.items() if v is not None}
        data = await self._execute(query, {"object": obj})
        b = data["insert_briefs_one"]
        return Brief(
            id=b.get("id"),
            user_phone=b.get("user_phone"),
            type=BriefType(b.get("type")),
            task_ids=b.get("task_ids") or [],
            recurring_task_ids=b.get("recurring_task_ids") or [],
            content_summary=b.get("content_summary"),
            user_engaged=b.get("user_engaged", False),
            response_time_seconds=b.get("response_time_seconds"),
            sent_at=b.get("sent_at"),
        )

    # ============================================
    # SCHEDULED TRIGGER OPERATIONS
    # ============================================

    async def create_trigger(self, trigger: ScheduledTrigger) -> ScheduledTrigger:
        """Create a scheduled trigger."""
        query = """
        mutation CreateTrigger($object: scheduled_triggers_insert_input!) {
            insert_scheduled_triggers_one(object: $object) {
                id user_phone trigger_type task_id recurring_task_id
                trigger_at status triggered_at metadata created_at
            }
        }
        """
        obj = {
            "user_phone": trigger.user_phone,
            "trigger_type": trigger.trigger_type.value if isinstance(trigger.trigger_type, TriggerType) else trigger.trigger_type,
            "task_id": trigger.task_id,
            "recurring_task_id": trigger.recurring_task_id,
            "trigger_at": trigger.trigger_at.isoformat() if trigger.trigger_at else None,
            "status": trigger.status,
            "metadata": trigger.metadata or {},
        }
        obj = {k: v for k, v in obj.items() if v is not None}
        data = await self._execute(query, {"object": obj})
        return self._parse_trigger(data["insert_scheduled_triggers_one"])

    async def get_pending_triggers(self, before: datetime) -> List[ScheduledTrigger]:
        """Get pending triggers before given time."""
        query = """
        query GetPendingTriggers($before: timestamptz!) {
            scheduled_triggers(
                where: {
                    trigger_at: {_lte: $before},
                    status: {_eq: "pending"}
                },
                order_by: {trigger_at: asc}
            ) {
                id user_phone trigger_type task_id recurring_task_id
                trigger_at status triggered_at metadata created_at
            }
        }
        """
        data = await self._execute(query, {"before": before.isoformat()})
        return [self._parse_trigger(t) for t in data.get("scheduled_triggers", [])]

    async def mark_trigger_done(self, trigger_id: str) -> Optional[ScheduledTrigger]:
        """Mark trigger as triggered."""
        query = """
        mutation MarkTriggerDone($id: uuid!) {
            update_scheduled_triggers_by_pk(
                pk_columns: {id: $id},
                _set: {status: "triggered", triggered_at: "now()"}
            ) {
                id user_phone trigger_type task_id recurring_task_id
                trigger_at status triggered_at metadata created_at
            }
        }
        """
        data = await self._execute(query, {"id": trigger_id})
        t = data.get("update_scheduled_triggers_by_pk")
        if t:
            return self._parse_trigger(t)
        return None

    async def cancel_triggers_for_task(self, task_id: str) -> int:
        """Cancel all pending triggers for a task."""
        query = """
        mutation CancelTriggers($task_id: uuid!) {
            update_scheduled_triggers(
                where: {task_id: {_eq: $task_id}, status: {_eq: "pending"}},
                _set: {status: "cancelled"}
            ) {
                affected_rows
            }
        }
        """
        data = await self._execute(query, {"task_id": task_id})
        return data.get("update_scheduled_triggers", {}).get("affected_rows", 0)

    def _parse_trigger(self, t: Dict[str, Any]) -> ScheduledTrigger:
        """Parse trigger from GraphQL response."""
        return ScheduledTrigger(
            id=t.get("id"),
            user_phone=t.get("user_phone"),
            trigger_type=TriggerType(t.get("trigger_type")) if t.get("trigger_type") else None,
            task_id=t.get("task_id"),
            recurring_task_id=t.get("recurring_task_id"),
            trigger_at=t.get("trigger_at"),
            status=t.get("status", "pending"),
            triggered_at=t.get("triggered_at"),
            metadata=t.get("metadata") or {},
            created_at=t.get("created_at"),
        )

    # ============================================
    # LEGACY OPERATIONS (backward compatibility)
    # ============================================

    async def save_chat(self, chat: Chat) -> Chat:
        """Save a chat message (legacy)."""
        query = """
        mutation SaveChat($object: chats_insert_input!) {
            insert_chats_one(object: $object) {
                id phone_no chat type created_at updated_at
            }
        }
        """
        obj = {
            "phone_no": chat.phone_no,
            "chat": chat.chat,
            "type": chat.type,
        }
        data = await self._execute(query, {"object": obj})
        return Chat(**data["insert_chats_one"])

    async def get_chats(self, phone: str, limit: int = 20) -> List[Chat]:
        """Get recent chats for a phone number (legacy)."""
        query = """
        query GetChats($phone: String!, $limit: Int!) {
            chats(
                where: {phone_no: {_eq: $phone}},
                order_by: {created_at: desc},
                limit: $limit
            ) {
                id phone_no chat type created_at updated_at
            }
        }
        """
        data = await self._execute(query, {"phone": phone, "limit": limit})
        chats = data.get("chats", [])
        return [Chat(**c) for c in reversed(chats)]

    async def delete_chats(self, phone: str) -> int:
        """Delete all chats for a phone (legacy)."""
        query = """
        mutation DeleteChats($phone: String!) {
            delete_chats(where: {phone_no: {_eq: $phone}}) {
                affected_rows
            }
        }
        """
        data = await self._execute(query, {"phone": phone})
        return data.get("delete_chats", {}).get("affected_rows", 0)

    async def get_due_schedules(self, before: datetime) -> List[Schedule]:
        """Get schedules due before given time (legacy)."""
        query = """
        query GetDueSchedules($before: timestamptz!) {
            schedule(
                where: {
                    call_time: {_lte: $before},
                    call_status: {_eq: "pending"},
                    reminder_sent: {_eq: false}
                },
                order_by: {call_time: asc}
            ) {
                id user_id phone_number call_time context call_status task_status
                habit_type importance reminder_method rich_context follow_up_time
                follow_up_count reminder_sent is_recurring recurrence_rule
                created_at updated_at
            }
        }
        """
        data = await self._execute(query, {"before": before.isoformat()})
        return [Schedule(**s) for s in data.get("schedule", [])]

    async def update_schedule(self, schedule_id: str, updates: Dict[str, Any]) -> Optional[Schedule]:
        """Update schedule fields (legacy)."""
        query = """
        mutation UpdateSchedule($id: uuid!, $set: schedule_set_input!) {
            update_schedule_by_pk(pk_columns: {id: $id}, _set: $set) {
                id user_id phone_number call_time context call_status task_status
                habit_type importance reminder_method rich_context follow_up_time
                follow_up_count reminder_sent is_recurring recurrence_rule
                created_at updated_at
            }
        }
        """
        data = await self._execute(query, {"id": schedule_id, "set": updates})
        result = data.get("update_schedule_by_pk")
        if result:
            return Schedule(**result)
        return None


# Singleton instance
_db_client_v2: Optional[NhostClientV2] = None


def get_database_client_v2() -> NhostClientV2:
    """Get the singleton v2 database client."""
    global _db_client_v2
    if _db_client_v2 is None:
        endpoint = os.getenv("NHOST_GRAPHQL_ENDPOINT")
        secret = os.getenv("NHOST_ADMIN_SECRET")

        if not endpoint or not secret:
            raise ValueError(
                "Database not configured. Set NHOST_GRAPHQL_ENDPOINT and NHOST_ADMIN_SECRET"
            )

        logger.info(f"Using Nhost v2 database: {endpoint}")
        _db_client_v2 = NhostClientV2(endpoint, secret)

    return _db_client_v2


__all__ = ["NhostClientV2", "get_database_client_v2"]
