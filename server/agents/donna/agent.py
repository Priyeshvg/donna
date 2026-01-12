"""Donna Agent - Core agent logic and tool definitions."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from ...services.database import get_database_client, User, Schedule, Chat
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
        }
    ]


class DonnaAgent:
    """Donna Agent - handles tool execution."""

    def __init__(self, phone: str, user: Optional[User] = None):
        self.phone = phone
        self.user = user
        self.db = get_database_client()
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

        from datetime import timedelta
        time_max = datetime.now() + timedelta(days=days)
        slots = await self.calendar.find_free_time(duration_minutes, time_max=time_max)

        return {
            "slots": slots,
            "count": len(slots)
        }


__all__ = ["DonnaAgent", "SYSTEM_PROMPT", "get_tools_schema"]
