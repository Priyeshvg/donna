"""Reminder scheduler - fires due reminders via WhatsApp."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Set

from ..database import get_database_client, Schedule
from ..whatsapp import get_whatsapp_client
from ...logging_config import logger


class ReminderScheduler:
    """Background scheduler that fires due reminders."""

    POLL_INTERVAL = 30  # Check every 30 seconds
    LOOKAHEAD_SECONDS = 60  # Fire reminders due in next 60 seconds

    def __init__(self):
        self.db = get_database_client()
        self.whatsapp = get_whatsapp_client()
        self._running = False
        self._in_flight: Set[str] = set()  # Track reminders being processed

    async def start(self):
        """Start the scheduler loop."""
        self._running = True
        logger.info("Reminder scheduler started")

        while self._running:
            try:
                await self._check_and_fire_reminders()
            except Exception as e:
                logger.error(f"Scheduler error: {e}")

            await asyncio.sleep(self.POLL_INTERVAL)

    def stop(self):
        """Stop the scheduler."""
        self._running = False
        logger.info("Reminder scheduler stopped")

    async def _check_and_fire_reminders(self):
        """Check for due reminders and fire them."""
        now = datetime.now()
        cutoff = now + timedelta(seconds=self.LOOKAHEAD_SECONDS)

        # Get due reminders
        due_reminders = await self.db.get_due_schedules(cutoff)

        for reminder in due_reminders:
            # Skip if already being processed
            if reminder.id in self._in_flight:
                continue

            # Mark as in-flight
            self._in_flight.add(reminder.id)

            try:
                await self._fire_reminder(reminder)
            except Exception as e:
                logger.error(f"Failed to fire reminder {reminder.id}: {e}")
            finally:
                self._in_flight.discard(reminder.id)

    async def _fire_reminder(self, reminder: Schedule):
        """Fire a single reminder."""
        logger.info(f"Firing reminder {reminder.id} for {reminder.phone_number}: {reminder.context}")

        # Build reminder message
        message = self._format_reminder_message(reminder)

        # Send via appropriate method
        if reminder.reminder_method == "call":
            # For now, send WhatsApp and note that call was requested
            # TODO: Integrate ElevenLabs call
            message = f"📞 Call reminder: {reminder.context}\n\n(Voice call feature coming soon)"

        # Send WhatsApp message
        if not self.whatsapp:
            logger.warning(f"WhatsApp not configured - cannot send reminder {reminder.id}")
            # Mark as sent to avoid retry loop
            await self.db.update_schedule(reminder.id, {
                "reminder_sent": True,
                "call_status": "completed"
            })
            return

        success = await self.whatsapp.send_text(reminder.phone_number, message)

        if success:
            # Mark as sent
            await self.db.update_schedule(reminder.id, {
                "reminder_sent": True,
                "call_status": "completed" if not reminder.is_recurring else "pending"
            })

            # Handle recurrence
            if reminder.is_recurring and reminder.recurrence_rule:
                await self._schedule_next_occurrence(reminder)
        else:
            logger.error(f"Failed to send reminder {reminder.id}")

    def _format_reminder_message(self, reminder: Schedule) -> str:
        """Format the reminder message."""
        # Get importance emoji
        emoji = {
            "high": "🔴",
            "medium": "🟡",
            "low": "🟢"
        }.get(reminder.importance, "⏰")

        # Format time nicely
        if reminder.call_time:
            time_str = reminder.call_time.strftime("%I:%M %p")
        else:
            time_str = "now"

        # Build message
        message = f"{emoji} Reminder ({time_str})\n\n{reminder.context}"

        # Add rich context if available
        if reminder.rich_context:
            notes = reminder.rich_context.get("notes", [])
            if notes:
                message += f"\n\nNotes: {', '.join(notes)}"

        return message

    async def _schedule_next_occurrence(self, reminder: Schedule):
        """Schedule next occurrence for recurring reminder."""
        # TODO: Implement RRULE parsing for complex recurrence
        # For now, skip - would need dateutil.rrule

        logger.info(f"Recurring reminder {reminder.id} - next occurrence would be scheduled")


# Global scheduler instance
_scheduler: ReminderScheduler = None


async def start_scheduler():
    """Start the global reminder scheduler."""
    global _scheduler
    if _scheduler is None:
        _scheduler = ReminderScheduler()
        asyncio.create_task(_scheduler.start())
        return _scheduler
    return _scheduler


__all__ = ["ReminderScheduler", "start_scheduler"]
