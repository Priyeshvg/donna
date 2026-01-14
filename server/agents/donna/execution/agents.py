"""Donna Execution Agents - handle reminders, memory, calendar, etc."""

from datetime import datetime, timedelta
import re
from typing import Any, Dict, Optional

from ....logging_config import logger
from ....services.database import get_database_client, Schedule, User
from ....services.memory import get_memory_client
from ....services.calendar import get_calendar_client


def _parse_time(time_str: str) -> Optional[datetime]:
    """Parse various time formats into datetime.

    Supports:
    - ISO format: 2024-01-14T21:00:00
    - Time only: 9pm, 9:00pm, 21:00, 9:30 pm
    - Relative: in 2 mins, in 5 minutes, in 1 hour
    """
    if not time_str:
        return None

    time_str = time_str.strip().lower()
    now = datetime.now()

    # Try ISO format first
    try:
        return datetime.fromisoformat(time_str)
    except ValueError:
        pass

    # Try relative time (in X mins/minutes/hours)
    relative_match = re.match(r'in\s+(\d+)\s*(min|mins|minutes?|hour|hours?|hr|hrs?)', time_str)
    if relative_match:
        amount = int(relative_match.group(1))
        unit = relative_match.group(2)
        if 'hour' in unit or 'hr' in unit:
            return now + timedelta(hours=amount)
        else:
            return now + timedelta(minutes=amount)

    # Try time only formats (9pm, 9:00pm, 21:00, etc.)
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

        result = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

        # If time has passed today, schedule for tomorrow
        if result <= now:
            result += timedelta(days=1)

        return result

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


async def _handle_reminder(
    phone: str,
    user: User,
    action: str,
    params: Dict[str, Any]
) -> Dict[str, Any]:
    """Handle reminder actions."""
    db = get_database_client()

    if action == "create":
        # Create a reminder
        call_time_str = params.get("time")
        context = params.get("context", "Reminder")

        if not call_time_str:
            return {"success": False, "error": "Missing time parameter"}

        call_time = _parse_time(call_time_str)
        if not call_time:
            return {"success": False, "error": f"Could not parse time: {call_time_str}"}

        schedule = Schedule(
            phone_number=phone,
            context=context,
            call_time=call_time,
            importance=params.get("importance", "medium"),
            reminder_method="whatsapp",
            call_status="pending",
            task_status="pending"
        )
        created = await db.create_schedule(schedule)

        # Increment usage count
        await _increment_usage(phone, user, "reminder_count")

        return {
            "success": True,
            "reminder_id": created.id,
            "time": call_time.isoformat(),
            "context": context
        }

    elif action == "list":
        schedules = await db.get_schedules(phone, "pending")
        reminders = [
            {
                "id": s.id,
                "context": s.context,
                "time": s.call_time.isoformat() if s.call_time else None,
            }
            for s in schedules
        ]
        return {"success": True, "reminders": reminders}

    elif action == "delete":
        reminder_id = params.get("id")
        if reminder_id:
            await db.update_schedule(reminder_id, {"call_status": "cancelled"})
        else:
            await db.delete_schedules(phone)
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
