"""Donna Execution Agents - handle reminders, memory, calendar, etc."""

from datetime import datetime, timedelta, timezone
import re
from typing import Any, Dict, Optional

from ....logging_config import logger
from ....services.database import get_database_client, Schedule, User
from ....services.database.client_v2 import NhostClientV2
from ....services.database.models import (
    Task, TaskStatus, ScheduledTrigger, TriggerType,
    TaskInteraction, InteractionType, InteractionContext
)
from ....services.memory import get_memory_client
from ....services.calendar import get_calendar_client
import os


# IST timezone offset (UTC+5:30)
IST = timezone(timedelta(hours=5, minutes=30))
UTC = timezone.utc


def _get_ist_now() -> datetime:
    """Get current time in IST."""
    return datetime.now(IST)


def _ist_to_utc(dt: datetime) -> datetime:
    """Convert IST datetime to UTC for storage."""
    if dt.tzinfo is None:
        # Assume naive datetime is IST
        dt = dt.replace(tzinfo=IST)
    return dt.astimezone(UTC).replace(tzinfo=None)  # Store as naive UTC


def _utc_to_ist(dt: datetime) -> datetime:
    """Convert UTC datetime to IST for display."""
    if dt.tzinfo is None:
        # Assume naive datetime is UTC
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(IST)


def _format_ist_time(dt: datetime) -> str:
    """Format datetime for display in IST."""
    ist_dt = _utc_to_ist(dt)
    return ist_dt.strftime("%I:%M %p").lstrip("0").lower()  # e.g., "9:00 pm"


def _parse_time(time_str: str) -> Optional[datetime]:
    """Parse various time formats into datetime.

    User input is interpreted as IST, but we return UTC for storage.
    Supports:
    - ISO format: 2024-01-14T21:00:00
    - Time only: 9pm, 9:00pm, 21:00, 9:30 pm
    - Relative: in 2 mins, in 5 minutes, in 1 hour
    - Tomorrow: tomorrow 7pm, tomorrow at 9:00
    """
    if not time_str:
        return None

    time_str = time_str.strip().lower()
    now_ist = _get_ist_now()  # Use IST for parsing user times

    # Try ISO format first
    try:
        parsed = datetime.fromisoformat(time_str)
        return _ist_to_utc(parsed)  # Convert to UTC
    except ValueError:
        pass

    # Try relative time (in X mins/minutes/hours)
    relative_match = re.match(r'in\s+(\d+)\s*(min|mins|minutes?|hour|hours?|hr|hrs?)', time_str)
    if relative_match:
        amount = int(relative_match.group(1))
        unit = relative_match.group(2)
        if 'hour' in unit or 'hr' in unit:
            result = now_ist + timedelta(hours=amount)
        else:
            result = now_ist + timedelta(minutes=amount)
        return _ist_to_utc(result)  # Convert to UTC

    # Check for "tomorrow" prefix
    is_tomorrow = False
    if time_str.startswith('tomorrow'):
        is_tomorrow = True
        # Remove "tomorrow" and optional "at" from the string
        time_str = re.sub(r'^tomorrow\s*(at\s*)?', '', time_str).strip()
        # If nothing left after removing tomorrow, default to 9am
        if not time_str:
            result = now_ist.replace(hour=9, minute=0, second=0, microsecond=0) + timedelta(days=1)
            return _ist_to_utc(result)  # Convert to UTC

    # Try time only formats (9pm, 9:00pm, 21:00, 7 pm, etc.)
    time_match = re.match(r'(\d{1,2})(?::(\d{2}))?\s*(am|pm)?', time_str)
    if time_match:
        hour = int(time_match.group(1))
        minute = int(time_match.group(2) or 0)
        period = time_match.group(3)

        # Convert to 24-hour format
        if period == 'pm' and hour != 12:
            hour += 12
        elif period == 'am' and hour == 12:
            hour = 0

        result = now_ist.replace(hour=hour, minute=minute, second=0, microsecond=0)

        # If tomorrow flag set, always add a day
        if is_tomorrow:
            result += timedelta(days=1)
        # Otherwise, if time has passed today, schedule for tomorrow
        elif result <= now_ist:
            result += timedelta(days=1)

        return _ist_to_utc(result)  # Convert to UTC

    return None


async def execute_agent_task(
    phone: str,
    user: User,
    task: Dict[str, Any]
) -> Dict[str, Any]:
    """Execute a task dispatched by the interaction agent.

    Args:
        phone: User's phone number
        user: User object
        task: Dict with agent, action, params

    Returns:
        Dict with success status and result
    """
    agent = task.get("agent")
    action = task.get("action")
    params = task.get("params", {})

    logger.info(f"Executing agent task: {agent}.{action}")

    try:
        if agent == "reminder":
            return await _handle_reminder(phone, user, action, params)
        elif agent == "memory":
            return await _handle_memory(phone, user, action, params)
        elif agent == "calendar":
            return await _handle_calendar(phone, action, params)
        elif agent == "reset":
            return await _handle_reset(phone)
        else:
            return {"success": False, "error": f"Unknown agent: {agent}"}
    except Exception as e:
        logger.error(f"Agent task failed: {agent}.{action} - {e}")
        return {"success": False, "error": str(e)}


def _get_db_v2() -> NhostClientV2:
    """Get v2 database client."""
    return NhostClientV2(
        endpoint=os.getenv("NHOST_HASURA_URL_V2") or os.getenv("NHOST_HASURA_URL") or os.getenv("NHOST_GRAPHQL_ENDPOINT"),
        admin_secret=os.getenv("NHOST_ADMIN_SECRET")
    )


async def _handle_reminder(
    phone: str,
    user: User,
    action: str,
    params: Dict[str, Any]
) -> Dict[str, Any]:
    """Handle reminder actions using v2 database."""
    db = get_database_client()
    db_v2 = _get_db_v2()

    if action == "create":
        # Create a reminder
        call_time_str = params.get("time")
        # Accept both 'task' (new) and 'context' (old) for task description
        task_description = params.get("task") or params.get("context") or "Reminder"

        if not call_time_str:
            return {"success": False, "error": "Missing time parameter"}

        call_time = _parse_time(call_time_str)
        if not call_time:
            return {"success": False, "error": f"Could not parse time: {call_time_str}"}

        # Use v2 Task model
        task = Task(
            user_phone=phone,
            title=task_description,
            status=TaskStatus.PENDING,
            remind_at=call_time,
        )
        created = await db_v2.create_task(task)

        # Create scheduled trigger for the reminder
        await db_v2.create_trigger(ScheduledTrigger(
            user_phone=phone,
            trigger_type=TriggerType.TASK_REMINDER,
            task_id=created.id,
            trigger_at=call_time,
            status="pending",
        ))

        # Log the interaction
        await db_v2.log_interaction(TaskInteraction(
            user_phone=phone,
            task_id=created.id,
            type=InteractionType.CREATED,
            context=InteractionContext.DIRECT,
        ))

        # Increment usage count
        await _increment_usage(phone, user, "reminder_count")

        # Format time nicely for display (e.g., "9:00 pm" instead of ISO)
        friendly_time = _format_ist_time(call_time)

        return {
            "success": True,
            "reminder_id": created.id,
            "time": friendly_time,
            "time_iso": call_time.isoformat(),
            "task": task_description
        }

    elif action == "list":
        # Use v2 to get tasks
        tasks = await db_v2.get_pending_tasks(phone)
        reminders = [
            {
                "id": t.id,
                "task": t.title,
                "time": _format_ist_time(t.remind_at) if t.remind_at else None,
            }
            for t in tasks
        ]
        return {"success": True, "reminders": reminders}

    elif action == "update":
        reminder_id = params.get("id")
        if not reminder_id:
            return {"success": False, "error": "Missing reminder id"}

        updates = {}

        # Update time if provided
        if params.get("time"):
            new_time = _parse_time(params.get("time"))
            if new_time:
                updates["remind_at"] = new_time.isoformat()
                # Also update the trigger
                # TODO: Update scheduled_trigger time as well

        # Update task description if provided
        if params.get("task"):
            updates["title"] = params.get("task")

        if updates:
            await db_v2.update_task(reminder_id, updates)
            return {"success": True, "updated": updates}

        return {"success": False, "error": "No updates provided"}

    elif action == "delete":
        reminder_id = params.get("id")
        if reminder_id:
            await db_v2.update_task(reminder_id, {"status": TaskStatus.DROPPED.value})
            # Log the drop interaction
            await db_v2.log_interaction(TaskInteraction(
                user_phone=phone,
                task_id=reminder_id,
                type=InteractionType.DROPPED,
                context=InteractionContext.DIRECT,
            ))
        return {"success": True}

    else:
        return {"success": False, "error": f"Unknown reminder action: {action}"}


async def _handle_memory(
    phone: str,
    user: User,
    action: str,
    params: Dict[str, Any]
) -> Dict[str, Any]:
    """Handle memory actions."""
    memory = get_memory_client()
    if not memory:
        return {"success": False, "error": "Memory not configured"}

    if action == "store":
        content = params.get("content")
        if not content:
            return {"success": False, "error": "Missing content"}

        metadata = {
            "category": params.get("category"),
            "entity": params.get("entity"),
        }
        # Remove None values
        metadata = {k: v for k, v in metadata.items() if v}

        vector_id = await memory.store(phone, content, metadata)

        # Increment usage count
        await _increment_usage(phone, user, "memory_count")

        return {"success": True, "vector_id": vector_id}

    elif action == "search":
        query = params.get("query")
        if not query:
            return {"success": False, "error": "Missing query"}

        results = await memory.search(phone, query)
        return {"success": True, "results": results}

    elif action == "delete":
        await memory.delete_namespace(phone)
        return {"success": True}

    else:
        return {"success": False, "error": f"Unknown memory action: {action}"}


async def _handle_calendar(
    phone: str,
    action: str,
    params: Dict[str, Any]
) -> Dict[str, Any]:
    """Handle calendar actions."""
    calendar = get_calendar_client()
    if not calendar:
        return {"success": False, "error": "Calendar not configured"}

    if action == "list":
        from datetime import timedelta
        days = params.get("days", 7)
        time_max = datetime.now() + timedelta(days=days)
        events = await calendar.list_events(time_max=time_max)
        return {"success": True, "events": events}

    elif action == "create":
        start_time = datetime.fromisoformat(params.get("start_time"))
        end_time = datetime.fromisoformat(params["end_time"]) if params.get("end_time") else None

        event = await calendar.create_event(
            summary=params.get("summary", "Event"),
            start_time=start_time,
            end_time=end_time,
            description=params.get("description"),
            location=params.get("location"),
        )
        return {"success": True, "event": event}

    else:
        return {"success": False, "error": f"Unknown calendar action: {action}"}


async def _handle_reset(phone: str) -> Dict[str, Any]:
    """Reset all user data."""
    db = get_database_client()
    memory = get_memory_client()

    # Delete reminders
    await db.delete_schedules(phone)

    # Delete chats
    await db.delete_chats(phone)

    # Delete memory
    if memory:
        await memory.delete_namespace(phone)

    # Delete user
    await db.delete_user(phone)

    return {"success": True, "message": "All data deleted"}


async def _increment_usage(phone: str, user: User, stat_name: str) -> None:
    """Increment a usage stat in the onboarding field."""
    try:
        db = get_database_client()
        current_stats = user.onboarding or {
            "reminder_count": 0,
            "memory_count": 0,
            "message_count": 0,
        }
        current_stats[stat_name] = current_stats.get(stat_name, 0) + 1
        await db.update_user(phone, {"onboarding": current_stats})
    except Exception as e:
        logger.warning(f"Failed to increment usage stat: {e}")
