"""Google Calendar client via Composio SDK."""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from ...logging_config import logger

try:
    from composio import ComposioToolSet, Action
    COMPOSIO_AVAILABLE = True
except ImportError:
    COMPOSIO_AVAILABLE = False
    logger.warning("Composio SDK not installed - calendar features disabled")


class CalendarClient:
    """Google Calendar client using Composio SDK."""

    def __init__(self, api_key: str, user_id: Optional[str] = None):
        if not COMPOSIO_AVAILABLE:
            raise ImportError("Composio SDK required for calendar features")

        self.api_key = api_key
        self.user_id = user_id
        self.toolset = ComposioToolSet(api_key=api_key)

    def set_user(self, user_id: str):
        """Set the active user for calendar operations."""
        self.user_id = user_id

    async def list_events(
        self,
        time_min: Optional[datetime] = None,
        time_max: Optional[datetime] = None,
        max_results: int = 10
    ) -> List[Dict[str, Any]]:
        """List calendar events in a time range.

        Args:
            time_min: Start of range (default: now)
            time_max: End of range (default: 7 days from now)
            max_results: Maximum events to return

        Returns:
            List of calendar events
        """
        if not time_min:
            time_min = datetime.now()
        if not time_max:
            time_max = time_min + timedelta(days=7)

        try:
            result = self.toolset.execute_action(
                action=Action.GOOGLECALENDAR_LIST_EVENTS,
                params={
                    "timeMin": time_min.isoformat() + "Z",
                    "timeMax": time_max.isoformat() + "Z",
                    "maxResults": max_results,
                    "singleEvents": True,
                    "orderBy": "startTime"
                },
                entity_id=self.user_id
            )

            events = result.get("items", [])
            return self._format_events(events)

        except Exception as e:
            logger.error(f"Failed to list calendar events: {e}")
            return []

    async def create_event(
        self,
        summary: str,
        start_time: datetime,
        end_time: Optional[datetime] = None,
        description: Optional[str] = None,
        location: Optional[str] = None,
        attendees: Optional[List[str]] = None
    ) -> Optional[Dict[str, Any]]:
        """Create a new calendar event.

        Args:
            summary: Event title
            start_time: When event starts
            end_time: When event ends (default: 1 hour after start)
            description: Event description
            location: Event location
            attendees: List of email addresses to invite

        Returns:
            Created event or None if failed
        """
        if not end_time:
            end_time = start_time + timedelta(hours=1)

        event_body = {
            "summary": summary,
            "start": {
                "dateTime": start_time.isoformat(),
                "timeZone": "Asia/Kolkata"
            },
            "end": {
                "dateTime": end_time.isoformat(),
                "timeZone": "Asia/Kolkata"
            }
        }

        if description:
            event_body["description"] = description
        if location:
            event_body["location"] = location
        if attendees:
            event_body["attendees"] = [{"email": email} for email in attendees]

        try:
            result = self.toolset.execute_action(
                action=Action.GOOGLECALENDAR_CREATE_EVENT,
                params=event_body,
                entity_id=self.user_id
            )

            logger.info(f"Created calendar event: {summary}")
            return self._format_event(result)

        except Exception as e:
            logger.error(f"Failed to create calendar event: {e}")
            return None

    async def get_event(self, event_id: str) -> Optional[Dict[str, Any]]:
        """Get a specific calendar event by ID."""
        try:
            result = self.toolset.execute_action(
                action=Action.GOOGLECALENDAR_GET_EVENT,
                params={"eventId": event_id},
                entity_id=self.user_id
            )
            return self._format_event(result)
        except Exception as e:
            logger.error(f"Failed to get calendar event: {e}")
            return None

    async def update_event(
        self,
        event_id: str,
        updates: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Update a calendar event."""
        try:
            result = self.toolset.execute_action(
                action=Action.GOOGLECALENDAR_UPDATE_EVENT,
                params={"eventId": event_id, **updates},
                entity_id=self.user_id
            )
            return self._format_event(result)
        except Exception as e:
            logger.error(f"Failed to update calendar event: {e}")
            return None

    async def delete_event(self, event_id: str) -> bool:
        """Delete a calendar event."""
        try:
            self.toolset.execute_action(
                action=Action.GOOGLECALENDAR_DELETE_EVENT,
                params={"eventId": event_id},
                entity_id=self.user_id
            )
            logger.info(f"Deleted calendar event: {event_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete calendar event: {e}")
            return False

    async def find_free_time(
        self,
        duration_minutes: int = 60,
        time_min: Optional[datetime] = None,
        time_max: Optional[datetime] = None
    ) -> List[Dict[str, Any]]:
        """Find free time slots in the calendar.

        Args:
            duration_minutes: Length of free slot needed
            time_min: Start searching from (default: now)
            time_max: Stop searching at (default: 7 days)

        Returns:
            List of free time slots
        """
        if not time_min:
            time_min = datetime.now()
        if not time_max:
            time_max = time_min + timedelta(days=7)

        # Get all events in range
        events = await self.list_events(time_min, time_max, max_results=50)

        # Find gaps
        free_slots = []
        current_time = time_min

        for event in events:
            event_start = datetime.fromisoformat(event["start"].replace("Z", "+00:00"))

            # Check if there's a gap before this event
            gap = (event_start - current_time).total_seconds() / 60
            if gap >= duration_minutes:
                free_slots.append({
                    "start": current_time.isoformat(),
                    "end": event_start.isoformat(),
                    "duration_minutes": int(gap)
                })

            event_end = datetime.fromisoformat(event["end"].replace("Z", "+00:00"))
            if event_end > current_time:
                current_time = event_end

        # Check gap after last event
        gap = (time_max - current_time).total_seconds() / 60
        if gap >= duration_minutes:
            free_slots.append({
                "start": current_time.isoformat(),
                "end": time_max.isoformat(),
                "duration_minutes": int(gap)
            })

        return free_slots[:5]  # Return top 5 slots

    def _format_events(self, events: List[Dict]) -> List[Dict[str, Any]]:
        """Format a list of events for response."""
        return [self._format_event(e) for e in events]

    def _format_event(self, event: Dict) -> Dict[str, Any]:
        """Format a single event for response."""
        start = event.get("start", {})
        end = event.get("end", {})

        return {
            "id": event.get("id"),
            "summary": event.get("summary", "No title"),
            "start": start.get("dateTime") or start.get("date"),
            "end": end.get("dateTime") or end.get("date"),
            "location": event.get("location"),
            "description": event.get("description"),
            "attendees": [a.get("email") for a in event.get("attendees", [])],
            "link": event.get("htmlLink")
        }


# Singleton instance
_calendar_client: Optional[CalendarClient] = None


def get_calendar_client() -> Optional[CalendarClient]:
    """Get the singleton calendar client. Returns None if not configured."""
    global _calendar_client

    if _calendar_client is None:
        api_key = os.getenv("COMPOSIO_API_KEY")

        if not api_key:
            logger.warning("Composio not configured - calendar features disabled")
            return None

        if not COMPOSIO_AVAILABLE:
            return None

        _calendar_client = CalendarClient(api_key)

    return _calendar_client


__all__ = ["CalendarClient", "get_calendar_client"]
