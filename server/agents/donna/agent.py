"""Donna Agent - Core agent logic and tool definitions."""

from __future__ import annotations

from datetime import datetime, timedelta, date
from pathlib import Path
from typing import Any, Dict, List, Optional

from ...services.database import get_database_client, User, Schedule, Chat
from ...services.database.client_v2 import get_database_client_v2
from ...services.database.models import (
    Task, TaskStatus, TaskAccountability,
    RecurringTask, RecurringTaskStatus, RecurringSchedule, RecurringMetric,
    RecurringTaskLog,
    TaskInteraction, InteractionType, InteractionContext,
    ScheduledTrigger, TriggerType,
)
from ...services.memory import get_memory_client
from ...services.whatsapp import get_whatsapp_client, OutgoingMessage, ImageMessage
from ...services.calendar import get_calendar_client
from ...logging_config import logger


# Load system prompt
_PROMPT_PATH = Path(__file__).parent / "system_prompt.md"
SYSTEM_PROMPT = _PROMPT_PATH.read_text(encoding="utf-8").strip()


def get_tools_schema() -> List[Dict[str, Any]]:
    """Return tool definitions for the LLM."""
    return [
        {
            "type": "function",
            "function": {
                "name": "send_whatsapp",
                "description": "Send a WhatsApp message to the user. Use this for all responses.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "message": {
                            "type": "string",
                            "description": "The message to send"
                        }
                    },
                    "required": ["message"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "send_image",
                "description": "Send an image with optional caption (e.g., pin instruction)",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "image_url": {
                            "type": "string",
                            "description": "URL of the image to send"
                        },
                        "caption": {
                            "type": "string",
                            "description": "Optional caption for the image"
                        }
                    },
                    "required": ["image_url"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "create_reminder",
                "description": "Create a reminder/schedule for the user",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "context": {
                            "type": "string",
                            "description": "What to remind about"
                        },
                        "call_time": {
                            "type": "string",
                            "description": "When to remind (ISO format: YYYY-MM-DDTHH:mm:ss+05:30)"
                        },
                        "importance": {
                            "type": "string",
                            "enum": ["low", "medium", "high"],
                            "description": "Importance level"
                        },
                        "reminder_method": {
                            "type": "string",
                            "enum": ["whatsapp", "call"],
                            "description": "How to remind (default: whatsapp)"
                        }
                    },
                    "required": ["context", "call_time"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "list_reminders",
                "description": "Get the user's pending reminders",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "status": {
                            "type": "string",
                            "enum": ["pending", "completed", "all"],
                            "description": "Filter by status (default: pending)"
                        }
                    }
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "update_reminder",
                "description": "Update an existing reminder",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "reminder_id": {
                            "type": "string",
                            "description": "ID of the reminder to update"
                        },
                        "context": {
                            "type": "string",
                            "description": "New context (optional)"
                        },
                        "call_time": {
                            "type": "string",
                            "description": "New time (optional)"
                        },
                        "call_status": {
                            "type": "string",
                            "enum": ["pending", "completed", "cancelled"],
                            "description": "New status (optional)"
                        }
                    },
                    "required": ["reminder_id"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "delete_reminders",
                "description": "Delete all reminders for the user",
                "parameters": {
                    "type": "object",
                    "properties": {}
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "store_memory",
                "description": "Store important information in long-term memory (birthdays, preferences, facts about people)",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "content": {
                            "type": "string",
                            "description": "The information to remember"
                        },
                        "metadata": {
                            "type": "object",
                            "description": "Additional context (person, type, etc.)",
                            "properties": {
                                "type": {"type": "string"},
                                "person": {"type": "string"},
                                "category": {"type": "string"}
                            }
                        }
                    },
                    "required": ["content"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "search_memory",
                "description": "Search long-term memory for relevant information",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "What to search for"
                        }
                    },
                    "required": ["query"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "get_user_profile",
                "description": "Get user's profile and preferences",
                "parameters": {
                    "type": "object",
                    "properties": {}
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "update_user_profile",
                "description": "Update user's profile (name, preferences, onboarding state, pin_status)",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "default_reminder_method": {
                            "type": "string",
                            "enum": ["whatsapp", "call"]
                        },
                        "pin_status": {
                            "type": "string",
                            "description": "Set to 'shown' after showing pin instruction"
                        },
                        "onboarding": {
                            "type": "object",
                            "properties": {
                                "step": {"type": "integer"},
                                "intro_shown": {"type": "boolean"},
                                "first_reminder": {"type": "boolean"},
                                "preference_asked": {"type": "boolean"}
                            }
                        }
                    }
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "reset_user",
                "description": "Delete all user data (reminders, chats, memories, profile). Only use after user confirms.",
                "parameters": {
                    "type": "object",
                    "properties": {}
                }
            }
        },
        # Calendar tools
        {
            "type": "function",
            "function": {
                "name": "list_calendar_events",
                "description": "List upcoming calendar events",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "days": {
                            "type": "integer",
                            "description": "Number of days to look ahead (default: 7)"
                        }
                    }
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "create_calendar_event",
                "description": "Create a new calendar event",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "summary": {
                            "type": "string",
                            "description": "Event title"
                        },
                        "start_time": {
                            "type": "string",
                            "description": "Start time (ISO format)"
                        },
                        "end_time": {
                            "type": "string",
                            "description": "End time (ISO format, optional - defaults to 1 hour)"
                        },
                        "description": {
                            "type": "string",
                            "description": "Event description"
                        },
                        "location": {
                            "type": "string",
                            "description": "Event location"
                        },
                        "attendees": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "List of email addresses to invite"
                        }
                    },
                    "required": ["summary", "start_time"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "find_free_time",
                "description": "Find available time slots in the calendar",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "duration_minutes": {
                            "type": "integer",
                            "description": "Length of free slot needed in minutes (default: 60)"
                        },
                        "days": {
                            "type": "integer",
                            "description": "Number of days to search (default: 7)"
                        }
                    }
                }
            }
        },
        # ============================================
        # NEW TASK TOOLS (v2 schema)
        # ============================================
        {
            "type": "function",
            "function": {
                "name": "create_task",
                "description": "Create a one-time task/reminder. Use smart defaults if time not specified.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "title": {
                            "type": "string",
                            "description": "What to do (e.g., 'Call Mom', 'Send invoice')"
                        },
                        "remind_at": {
                            "type": "string",
                            "description": "When to remind (ISO format). If not provided, uses smart defaults."
                        },
                        "due_date": {
                            "type": "string",
                            "description": "Hard deadline date (YYYY-MM-DD) if different from remind_at"
                        },
                        "priority": {
                            "type": "integer",
                            "description": "1=urgent, 2=high, 3=normal, 4=low. Default: 3",
                            "minimum": 1,
                            "maximum": 4
                        },
                        "description": {
                            "type": "string",
                            "description": "Additional details about the task"
                        }
                    },
                    "required": ["title"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "create_recurring_task",
                "description": "Create a habit/routine that repeats. For things like 'drink water', 'exercise', 'meditate'.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "title": {
                            "type": "string",
                            "description": "The habit name (e.g., 'Drink water', 'Exercise', 'Read')"
                        },
                        "frequency": {
                            "type": "string",
                            "enum": ["daily", "weekly", "weekdays", "weekends"],
                            "description": "How often (default: daily)"
                        },
                        "times_per_day": {
                            "type": "integer",
                            "description": "How many times per day (default: 1, water=4)",
                            "minimum": 1,
                            "maximum": 10
                        },
                        "reminder_times": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Times to remind (HH:MM format, e.g., ['09:00', '12:00']). Uses smart defaults if not provided."
                        },
                        "metric_unit": {
                            "type": "string",
                            "description": "Unit to track (e.g., 'glasses', 'steps', 'pages', 'minutes')"
                        },
                        "metric_goal": {
                            "type": "number",
                            "description": "Daily goal for the metric (e.g., 8 glasses, 10000 steps)"
                        },
                        "description": {
                            "type": "string",
                            "description": "Additional details about the habit"
                        }
                    },
                    "required": ["title"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "complete_task",
                "description": "Mark a task as done. Search by title if no ID.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "task_id": {
                            "type": "string",
                            "description": "Task ID (if known)"
                        },
                        "title_search": {
                            "type": "string",
                            "description": "Search by title/keyword (if ID not known)"
                        },
                        "metric_value": {
                            "type": "number",
                            "description": "For habits with metrics, the value achieved (e.g., 8 glasses)"
                        }
                    }
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "drop_task",
                "description": "Drop/cancel a task. User said 'forget it' or 'drop'.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "task_id": {
                            "type": "string",
                            "description": "Task ID (if known)"
                        },
                        "title_search": {
                            "type": "string",
                            "description": "Search by title/keyword (if ID not known)"
                        }
                    }
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "snooze_task",
                "description": "Snooze a task. User said 'later' or 'not now'.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "task_id": {
                            "type": "string",
                            "description": "Task ID (if known)"
                        },
                        "title_search": {
                            "type": "string",
                            "description": "Search by title/keyword (if ID not known)"
                        },
                        "hours": {
                            "type": "integer",
                            "description": "Hours to snooze (default: 4-5 hours)"
                        }
                    }
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "search_tasks",
                "description": "Search user's tasks and habits",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search term"
                        },
                        "include_completed": {
                            "type": "boolean",
                            "description": "Include completed tasks (default: false)"
                        },
                        "include_habits": {
                            "type": "boolean",
                            "description": "Include recurring tasks/habits (default: true)"
                        }
                    }
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "update_user",
                "description": "Update user's name or preferences",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "User's name"
                        },
                        "timezone": {
                            "type": "string",
                            "description": "Timezone (default: Asia/Kolkata)"
                        },
                        "morning_brief_time": {
                            "type": "string",
                            "description": "When to send morning brief (HH:MM)"
                        },
                        "evening_checkin_time": {
                            "type": "string",
                            "description": "When to send evening check-in (HH:MM)"
                        }
                    }
                }
            }
        }
    ]


class DonnaAgent:
    """Donna Agent - handles tool execution."""

    def __init__(self, phone: str, user: Optional[User] = None):
        self.phone = phone
        self.user = user
        self.db = get_database_client()
        self.db_v2 = get_database_client_v2()  # New schema
        self.memory = get_memory_client()
        self.whatsapp = get_whatsapp_client()
        self.calendar = get_calendar_client()

    async def execute_tool(self, tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a tool and return the result."""
        logger.info(f"Executing tool: {tool_name} with args: {args}")

        try:
            if tool_name == "send_whatsapp":
                return await self._send_whatsapp(args["message"])
            elif tool_name == "send_image":
                return await self._send_image(args["image_url"], args.get("caption"))
            elif tool_name == "create_reminder":
                return await self._create_reminder(args)
            elif tool_name == "list_reminders":
                return await self._list_reminders(args.get("status", "pending"))
            elif tool_name == "update_reminder":
                return await self._update_reminder(args)
            elif tool_name == "delete_reminders":
                return await self._delete_reminders()
            elif tool_name == "store_memory":
                return await self._store_memory(args["content"], args.get("metadata", {}))
            elif tool_name == "search_memory":
                return await self._search_memory(args["query"])
            elif tool_name == "get_user_profile":
                return await self._get_user_profile()
            elif tool_name == "update_user_profile":
                return await self._update_user_profile(args)
            elif tool_name == "reset_user":
                return await self._reset_user()
            # Calendar tools
            elif tool_name == "list_calendar_events":
                return await self._list_calendar_events(args.get("days", 7))
            elif tool_name == "create_calendar_event":
                return await self._create_calendar_event(args)
            elif tool_name == "find_free_time":
                return await self._find_free_time(args.get("duration_minutes", 60), args.get("days", 7))
            # NEW TASK TOOLS (v2)
            elif tool_name == "create_task":
                return await self._create_task_v2(args)
            elif tool_name == "create_recurring_task":
                return await self._create_recurring_task(args)
            elif tool_name == "complete_task":
                return await self._complete_task_v2(args)
            elif tool_name == "drop_task":
                return await self._drop_task(args)
            elif tool_name == "snooze_task":
                return await self._snooze_task(args)
            elif tool_name == "search_tasks":
                return await self._search_tasks(args)
            elif tool_name == "update_user":
                return await self._update_user_v2(args)
            else:
                return {"error": f"Unknown tool: {tool_name}"}
        except Exception as e:
            logger.error(f"Tool execution failed: {tool_name} - {e}")
            return {"error": str(e)}

    async def _send_whatsapp(self, message: str) -> Dict[str, Any]:
        """Send WhatsApp message.

        Note: We don't actually send via Meta API here - we return the message
        and let n8n handle the sending. This allows n8n to manage WhatsApp credentials.
        """
        # Save to chat history
        await self.db.save_chat(Chat(
            phone_no=self.phone,
            chat=message,
            type="sent"
        ))

        # Return success - n8n will send the actual message
        return {"success": True, "message": message, "pending_send": True}

    async def _send_image(self, image_url: str, caption: Optional[str] = None) -> Dict[str, Any]:
        """Send WhatsApp image.

        Note: We don't actually send via Meta API here - we return the image details
        and let n8n handle the sending.
        """
        # Return success - n8n will send the actual image
        return {"success": True, "image_url": image_url, "caption": caption, "pending_send": True}

    async def _create_reminder(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Create a reminder and increment usage count."""
        schedule = Schedule(
            phone_number=self.phone,
            context=args["context"],
            call_time=datetime.fromisoformat(args["call_time"]),
            importance=args.get("importance", "medium"),
            reminder_method=args.get("reminder_method", "whatsapp"),
            call_status="pending",
            task_status="pending"
        )
        created = await self.db.create_schedule(schedule)

        # Increment reminder count
        await self._increment_usage_stat("reminder_count")

        return {
            "success": True,
            "reminder_id": created.id,
            "context": created.context,
            "call_time": created.call_time.isoformat() if created.call_time else None
        }

    async def _list_reminders(self, status: str) -> Dict[str, Any]:
        """List user's reminders."""
        status_filter = None if status == "all" else "pending"
        schedules = await self.db.get_schedules(self.phone, status_filter)

        reminders = []
        for s in schedules:
            reminders.append({
                "id": s.id,
                "context": s.context,
                "call_time": s.call_time.isoformat() if s.call_time else None,
                "status": s.call_status,
                "importance": s.importance,
                "method": s.reminder_method
            })

        return {"reminders": reminders, "count": len(reminders)}

    async def _update_reminder(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Update a reminder."""
        reminder_id = args.pop("reminder_id")
        updates = {}

        if "context" in args:
            updates["context"] = args["context"]
        if "call_time" in args:
            updates["call_time"] = args["call_time"]
        if "call_status" in args:
            updates["call_status"] = args["call_status"]

        updated = await self.db.update_schedule(reminder_id, updates)
        if updated:
            return {"success": True, "reminder": {"id": updated.id, "context": updated.context}}
        return {"success": False, "error": "Reminder not found"}

    async def _delete_reminders(self) -> Dict[str, Any]:
        """Delete all reminders."""
        count = await self.db.delete_schedules(self.phone)
        return {"success": True, "deleted_count": count}

    async def _store_memory(self, content: str, metadata: Dict[str, Any]) -> Dict[str, Any]:
        """Store in vector memory and increment usage count."""
        if not self.memory:
            return {"success": False, "error": "Memory not configured"}

        vector_id = await self.memory.store(self.phone, content, metadata)

        # Increment memory count
        await self._increment_usage_stat("memory_count")

        return {"success": True, "vector_id": vector_id}

    async def _search_memory(self, query: str) -> Dict[str, Any]:
        """Search vector memory."""
        if not self.memory:
            return {"results": [], "error": "Memory not configured"}

        results = await self.memory.search(self.phone, query)
        return {"results": results}

    async def _get_user_profile(self) -> Dict[str, Any]:
        """Get user profile."""
        user = await self.db.get_user(self.phone)
        if user:
            return {
                "found": True,
                "name": user.name,
                "phone": user.phone_no,
                "default_reminder_method": user.default_reminder_method,
                "onboarding": user.onboarding,
                "pin_status": user.pin_status
            }
        return {"found": False}

    async def _update_user_profile(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Update user profile."""
        updated = await self.db.update_user(self.phone, args)
        if updated:
            return {"success": True, "user": {"name": updated.name, "onboarding": updated.onboarding}}
        return {"success": False, "error": "User not found"}

    async def _reset_user(self) -> Dict[str, Any]:
        """Reset all user data."""
        # Delete reminders
        await self.db.delete_schedules(self.phone)

        # Delete chats
        await self.db.delete_chats(self.phone)

        # Delete memory
        if self.memory:
            await self.memory.delete_namespace(self.phone)

        # Delete user
        await self.db.delete_user(self.phone)

        return {"success": True, "message": "All data deleted"}

    async def _increment_usage_stat(self, stat_name: str) -> None:
        """Increment a usage stat counter in the onboarding field."""
        try:
            if not self.user:
                return

            # Use onboarding field for usage tracking
            current_stats = self.user.onboarding or {
                "reminder_count": 0,
                "memory_count": 0,
                "message_count": 0,
            }
            current_stats[stat_name] = current_stats.get(stat_name, 0) + 1

            await self.db.update_user(self.phone, {"onboarding": current_stats})
            logger.debug(f"Incremented {stat_name} for {self.phone}")
        except Exception as e:
            logger.warning(f"Failed to increment usage stat: {e}")

    # Calendar methods
    async def _list_calendar_events(self, days: int) -> Dict[str, Any]:
        """List upcoming calendar events."""
        if not self.calendar:
            return {"events": [], "error": "Calendar not configured"}

        from datetime import timedelta
        time_max = datetime.now() + timedelta(days=days)
        events = await self.calendar.list_events(time_max=time_max)

        return {
            "events": events,
            "count": len(events)
        }

    async def _create_calendar_event(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Create a calendar event."""
        if not self.calendar:
            return {"success": False, "error": "Calendar not configured"}

        start_time = datetime.fromisoformat(args["start_time"])
        end_time = datetime.fromisoformat(args["end_time"]) if args.get("end_time") else None

        event = await self.calendar.create_event(
            summary=args["summary"],
            start_time=start_time,
            end_time=end_time,
            description=args.get("description"),
            location=args.get("location"),
            attendees=args.get("attendees")
        )

        if event:
            return {"success": True, "event": event}
        return {"success": False, "error": "Failed to create event"}

    async def _find_free_time(self, duration_minutes: int, days: int) -> Dict[str, Any]:
        """Find free time slots."""
        if not self.calendar:
            return {"slots": [], "error": "Calendar not configured"}

        time_max = datetime.now() + timedelta(days=days)
        slots = await self.calendar.find_free_time(duration_minutes, time_max=time_max)

        return {
            "slots": slots,
            "count": len(slots)
        }

    # ============================================
    # NEW TASK METHODS (v2 schema)
    # ============================================

    def _get_smart_default_time(self, title: str) -> datetime:
        """Get smart default reminder time based on task type.

        Smart defaults:
        - General reminder: Tomorrow 9am
        - Call/phone: Tomorrow 10am (business hours)
        - Exercise/gym: Tomorrow 7am (morning)
        - Read/reading: Tomorrow 9pm (evening)
        """
        # IST timezone offset
        now = datetime.utcnow() + timedelta(hours=5, minutes=30)
        tomorrow = now + timedelta(days=1)

        title_lower = title.lower()

        # Morning activities
        if any(word in title_lower for word in ["exercise", "gym", "workout", "run", "yoga", "meditate", "meditation"]):
            return tomorrow.replace(hour=7, minute=0, second=0, microsecond=0) - timedelta(hours=5, minutes=30)

        # Business hour activities
        if any(word in title_lower for word in ["call", "phone", "meeting", "email", "send"]):
            return tomorrow.replace(hour=10, minute=0, second=0, microsecond=0) - timedelta(hours=5, minutes=30)

        # Evening activities
        if any(word in title_lower for word in ["read", "reading", "book", "journal"]):
            return tomorrow.replace(hour=21, minute=0, second=0, microsecond=0) - timedelta(hours=5, minutes=30)

        # Default: Tomorrow 9am
        return tomorrow.replace(hour=9, minute=0, second=0, microsecond=0) - timedelta(hours=5, minutes=30)

    def _detect_recurring_pattern(self, title: str) -> Optional[Dict[str, Any]]:
        """Detect if task should be recurring and return pattern.

        Returns None if not detected as recurring, otherwise returns:
        {
            "frequency": "daily"|"weekly",
            "times_per_day": int,
            "reminder_times": ["HH:MM", ...],
            "metric": {"unit": str, "goal": float} or None
        }
        """
        title_lower = title.lower()

        # Water/hydration: 4x daily
        if any(word in title_lower for word in ["water", "hydrate", "hydration"]):
            return {
                "frequency": "daily",
                "times_per_day": 4,
                "reminder_times": ["09:00", "12:00", "16:00", "20:00"],
                "metric": {"unit": "glasses", "goal": 8}
            }

        # Exercise/workout: 1x morning
        if any(word in title_lower for word in ["exercise", "gym", "workout", "run", "yoga"]):
            return {
                "frequency": "daily",
                "times_per_day": 1,
                "reminder_times": ["07:00"],
                "metric": {"unit": "minutes", "goal": 30}
            }

        # Reading: 1x evening
        if any(word in title_lower for word in ["read", "reading", "book"]):
            return {
                "frequency": "daily",
                "times_per_day": 1,
                "reminder_times": ["21:00"],
                "metric": {"unit": "pages", "goal": 20}
            }

        # Meditation: 1x morning
        if any(word in title_lower for word in ["meditate", "meditation", "mindful"]):
            return {
                "frequency": "daily",
                "times_per_day": 1,
                "reminder_times": ["07:30"],
                "metric": {"unit": "minutes", "goal": 10}
            }

        # Walk: 1x evening
        if any(word in title_lower for word in ["walk", "walking", "steps"]):
            return {
                "frequency": "daily",
                "times_per_day": 1,
                "reminder_times": ["18:00"],
                "metric": {"unit": "steps", "goal": 6000}
            }

        # Journal: 1x evening
        if any(word in title_lower for word in ["journal", "journaling", "diary"]):
            return {
                "frequency": "daily",
                "times_per_day": 1,
                "reminder_times": ["21:30"],
                "metric": None
            }

        return None

    async def _create_task_v2(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Create a one-time task with smart defaults."""
        title = args["title"]

        # Get reminder time
        if args.get("remind_at"):
            remind_at = datetime.fromisoformat(args["remind_at"].replace("Z", "+00:00"))
        else:
            remind_at = self._get_smart_default_time(title)

        # Parse due date if provided
        due_date_obj = None
        if args.get("due_date"):
            due_date_obj = date.fromisoformat(args["due_date"])

        # Create task
        task = Task(
            user_phone=self.phone,
            title=title,
            description=args.get("description"),
            status=TaskStatus.PENDING,
            priority=args.get("priority", 3),
            remind_at=remind_at,
            due_date=due_date_obj,
            accountability=TaskAccountability(
                reminder_count=0,
                snooze_count=0,
                escalation_stage=0,
            ),
        )

        created = await self.db_v2.create_task(task)

        # Schedule first reminder trigger
        await self.db_v2.create_trigger(ScheduledTrigger(
            user_phone=self.phone,
            trigger_type=TriggerType.TASK_REMINDER,
            task_id=created.id,
            trigger_at=remind_at,
        ))

        # Log interaction
        await self.db_v2.log_interaction(TaskInteraction(
            user_phone=self.phone,
            task_id=created.id,
            type=InteractionType.CREATED,
            context=InteractionContext.DIRECT,
        ))

        # Format time for response (IST)
        ist_time = remind_at + timedelta(hours=5, minutes=30)
        time_str = ist_time.strftime("%I:%M %p").lstrip("0")
        date_str = "tomorrow" if ist_time.date() == (datetime.utcnow() + timedelta(days=1, hours=5, minutes=30)).date() else ist_time.strftime("%b %d")

        return {
            "success": True,
            "task_id": created.id,
            "title": created.title,
            "remind_at": created.remind_at.isoformat() if created.remind_at else None,
            "formatted_time": f"{date_str} {time_str}",
        }

    async def _create_recurring_task(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Create a recurring task/habit with smart defaults."""
        title = args["title"]

        # Try to detect pattern from title if not specified
        pattern = None
        if not args.get("frequency") and not args.get("times_per_day"):
            pattern = self._detect_recurring_pattern(title)

        # Use detected pattern or args
        frequency = args.get("frequency") or (pattern["frequency"] if pattern else "daily")
        times_per_day = args.get("times_per_day") or (pattern["times_per_day"] if pattern else 1)

        # Reminder times
        if args.get("reminder_times"):
            reminder_times = args["reminder_times"]
        elif pattern and pattern.get("reminder_times"):
            reminder_times = pattern["reminder_times"]
        else:
            # Default single reminder at 9am
            reminder_times = ["09:00"]

        # Metric
        metric = None
        if args.get("metric_unit"):
            metric = RecurringMetric(
                type=args.get("metric_type", "count"),
                unit=args["metric_unit"],
                target=args.get("metric_goal", 0),
            )
        elif pattern and pattern.get("metric"):
            metric = RecurringMetric(**pattern["metric"])

        # Calculate next reminder time
        now = datetime.utcnow()
        ist_now = now + timedelta(hours=5, minutes=30)

        # Find next reminder time
        next_reminder = None
        for time_str in sorted(reminder_times):
            hour, minute = map(int, time_str.split(":"))
            candidate = ist_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if candidate > ist_now:
                next_reminder = candidate - timedelta(hours=5, minutes=30)  # Back to UTC
                break

        if not next_reminder:
            # Use first time tomorrow
            hour, minute = map(int, reminder_times[0].split(":"))
            tomorrow = ist_now + timedelta(days=1)
            next_reminder = tomorrow.replace(hour=hour, minute=minute, second=0, microsecond=0) - timedelta(hours=5, minutes=30)

        # Create recurring task
        task = RecurringTask(
            user_phone=self.phone,
            title=title,
            description=args.get("description"),
            status=RecurringTaskStatus.ACTIVE,
            frequency=frequency,
            times_per_day=times_per_day,
            schedule=RecurringSchedule(
                times=reminder_times,
                days=[1, 2, 3, 4, 5, 6, 7],  # All days for daily
            ),
            streak_current=0,
            streak_best=0,
            metric=metric,
            next_reminder_at=next_reminder,
        )

        created = await self.db_v2.create_recurring_task(task)

        # Log interaction
        await self.db_v2.log_interaction(TaskInteraction(
            user_phone=self.phone,
            recurring_task_id=created.id,
            type=InteractionType.CREATED,
            context=InteractionContext.DIRECT,
        ))

        # Format response
        freq_text = f"{times_per_day}x" if times_per_day > 1 else ""
        times_text = ", ".join(reminder_times)
        metric_text = f" (tracking {metric.unit})" if metric else ""

        return {
            "success": True,
            "recurring_task_id": created.id,
            "title": created.title,
            "frequency": frequency,
            "times_per_day": times_per_day,
            "reminder_times": reminder_times,
            "formatted": f"{frequency} {freq_text} at {times_text}{metric_text}",
        }

    async def _complete_task_v2(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Mark a task as completed."""
        task_id = args.get("task_id")
        title_search = args.get("title_search")
        metric_value = args.get("metric_value")

        task = None
        recurring_task = None

        # Find task by ID or search
        if task_id:
            task = await self.db_v2.get_task(task_id)
            if not task:
                recurring_task = await self.db_v2.get_recurring_task(task_id)
        elif title_search:
            # Search one-time tasks
            tasks = await self.db_v2.get_tasks(self.phone, status=TaskStatus.PENDING)
            task = next(
                (t for t in tasks if title_search.lower() in t.title.lower()),
                None
            )
            if not task:
                # Search reminded tasks
                reminded_tasks = await self.db_v2.get_tasks(self.phone, status=TaskStatus.REMINDED)
                task = next(
                    (t for t in reminded_tasks if title_search.lower() in t.title.lower()),
                    None
                )
            if not task:
                # Search recurring tasks
                recurring_tasks = await self.db_v2.get_active_recurring_tasks(self.phone)
                recurring_task = next(
                    (t for t in recurring_tasks if title_search.lower() in t.title.lower()),
                    None
                )

        if task:
            # Complete one-time task
            await self.db_v2.complete_task(task.id)
            await self.db_v2.cancel_triggers_for_task(task.id)

            # Log interaction
            await self.db_v2.log_interaction(TaskInteraction(
                user_phone=self.phone,
                task_id=task.id,
                type=InteractionType.COMPLETED,
                context=InteractionContext.DIRECT,
            ))

            return {
                "success": True,
                "task_id": task.id,
                "title": task.title,
                "type": "task",
            }

        elif recurring_task:
            # Log completion for recurring task
            today = date.today()
            log = RecurringTaskLog(
                recurring_task_id=recurring_task.id,
                user_phone=self.phone,
                date=today,
                scheduled_count=recurring_task.times_per_day,
                completed_count=1,  # Increment
                streak_maintained=True,
            )
            await self.db_v2.log_recurring_task(log)

            # Update streak
            await self.db_v2.update_streak(recurring_task.id, increment=True)

            # Log interaction
            await self.db_v2.log_interaction(TaskInteraction(
                user_phone=self.phone,
                recurring_task_id=recurring_task.id,
                type=InteractionType.COMPLETED,
                context=InteractionContext.DIRECT,
            ))

            # Get updated task for streak info
            updated = await self.db_v2.get_recurring_task(recurring_task.id)
            streak = updated.streak_current if updated else 0

            return {
                "success": True,
                "recurring_task_id": recurring_task.id,
                "title": recurring_task.title,
                "type": "habit",
                "streak_current": streak,
            }

        return {"success": False, "error": "Task not found"}

    async def _drop_task(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Drop/cancel a task."""
        task_id = args.get("task_id")
        title_search = args.get("title_search")

        task = None

        # Find task
        if task_id:
            task = await self.db_v2.get_task(task_id)
        elif title_search:
            tasks = await self.db_v2.get_tasks(self.phone)
            task = next(
                (t for t in tasks if title_search.lower() in t.title.lower() and t.status != TaskStatus.COMPLETED),
                None
            )

        if task:
            await self.db_v2.drop_task(task.id)
            await self.db_v2.cancel_triggers_for_task(task.id)

            # Log interaction
            await self.db_v2.log_interaction(TaskInteraction(
                user_phone=self.phone,
                task_id=task.id,
                type=InteractionType.DROPPED,
                context=InteractionContext.DIRECT,
            ))

            return {
                "success": True,
                "task_id": task.id,
                "title": task.title,
            }

        return {"success": False, "error": "Task not found"}

    async def _snooze_task(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Snooze a task for later."""
        task_id = args.get("task_id")
        title_search = args.get("title_search")
        hours = args.get("hours", 5)  # Default 4-5 hours

        task = None

        # Find task
        if task_id:
            task = await self.db_v2.get_task(task_id)
        elif title_search:
            # Search reminded tasks first (most likely to snooze)
            reminded_tasks = await self.db_v2.get_tasks(self.phone, status=TaskStatus.REMINDED)
            task = next(
                (t for t in reminded_tasks if title_search.lower() in t.title.lower()),
                None
            )
            if not task:
                pending_tasks = await self.db_v2.get_tasks(self.phone, status=TaskStatus.PENDING)
                task = next(
                    (t for t in pending_tasks if title_search.lower() in t.title.lower()),
                    None
                )

        if task:
            # Cancel existing triggers
            await self.db_v2.cancel_triggers_for_task(task.id)

            # Schedule new reminder
            new_remind_at = datetime.utcnow() + timedelta(hours=hours)
            await self.db_v2.update_task(task.id, {
                "remind_at": new_remind_at.isoformat(),
                "status": "pending",
            })

            # Update accountability
            accountability = task.accountability or TaskAccountability()
            new_snooze_count = accountability.snooze_count + 1
            await self.db_v2.update_task(task.id, {
                "accountability": {
                    "reminder_count": accountability.reminder_count,
                    "snooze_count": new_snooze_count,
                    "escalation_stage": accountability.escalation_stage,
                    "last_interaction_at": datetime.utcnow().isoformat(),
                }
            })

            # Create new trigger
            await self.db_v2.create_trigger(ScheduledTrigger(
                user_phone=self.phone,
                trigger_type=TriggerType.TASK_REMINDER,
                task_id=task.id,
                trigger_at=new_remind_at,
            ))

            # Log interaction
            await self.db_v2.log_interaction(TaskInteraction(
                user_phone=self.phone,
                task_id=task.id,
                type=InteractionType.SNOOZED,
                context=InteractionContext.DIRECT,
            ))

            return {
                "success": True,
                "task_id": task.id,
                "title": task.title,
                "snoozed_until": new_remind_at.isoformat(),
                "snooze_count": new_snooze_count,
            }

        return {"success": False, "error": "Task not found"}

    async def _search_tasks(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Search user's tasks and habits."""
        query = args.get("query", "").lower()
        include_completed = args.get("include_completed", False)
        include_habits = args.get("include_habits", True)

        results = {
            "tasks": [],
            "habits": [],
        }

        # Get one-time tasks
        if include_completed:
            tasks = await self.db_v2.get_tasks(self.phone)
        else:
            pending = await self.db_v2.get_tasks(self.phone, status=TaskStatus.PENDING)
            reminded = await self.db_v2.get_tasks(self.phone, status=TaskStatus.REMINDED)
            tasks = pending + reminded

        for task in tasks:
            if not query or query in task.title.lower():
                results["tasks"].append({
                    "id": task.id,
                    "title": task.title,
                    "status": task.status.value if isinstance(task.status, TaskStatus) else task.status,
                    "remind_at": task.remind_at.isoformat() if task.remind_at else None,
                    "priority": task.priority,
                })

        # Get recurring tasks
        if include_habits:
            habits = await self.db_v2.get_active_recurring_tasks(self.phone)
            for habit in habits:
                if not query or query in habit.title.lower():
                    results["habits"].append({
                        "id": habit.id,
                        "title": habit.title,
                        "frequency": habit.frequency,
                        "times_per_day": habit.times_per_day,
                        "streak_current": habit.streak_current,
                        "streak_best": habit.streak_best,
                    })

        return {
            "success": True,
            "task_count": len(results["tasks"]),
            "habit_count": len(results["habits"]),
            **results,
        }

    async def _update_user_v2(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Update user in new schema."""
        from ...services.database.models import User as UserV2, UserPreferences

        # Get or create user
        user = await self.db_v2.get_user(self.phone)
        if not user:
            # Create new user
            user = await self.db_v2.create_user(UserV2(
                phone=self.phone,
                name=args.get("name"),
                timezone=args.get("timezone", "Asia/Kolkata"),
                preferences=UserPreferences(
                    morning_brief_time=args.get("morning_brief_time", "08:00"),
                    evening_checkin_time=args.get("evening_checkin_time", "21:00"),
                ),
            ))
            return {"success": True, "created": True, "name": user.name}

        # Update existing user
        updates = {}
        if args.get("name"):
            updates["name"] = args["name"]
        if args.get("timezone"):
            updates["timezone"] = args["timezone"]

        # Handle preferences
        prefs = user.preferences.model_dump() if user.preferences else {}
        if args.get("morning_brief_time"):
            prefs["morning_brief_time"] = args["morning_brief_time"]
        if args.get("evening_checkin_time"):
            prefs["evening_checkin_time"] = args["evening_checkin_time"]

        if prefs:
            updates["preferences"] = prefs

        if updates:
            updated = await self.db_v2.update_user(self.phone, updates)
            return {"success": True, "name": updated.name if updated else user.name}

        return {"success": True, "name": user.name}


__all__ = ["DonnaAgent", "SYSTEM_PROMPT", "get_tools_schema"]
