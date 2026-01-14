"""Task Scheduler - Polls every minute for tasks, reminders, check-ins, briefs.

This scheduler handles:
1. Task reminders (remind_at time passed)
2. Task check-ins (follow up on reminded tasks)
3. Recurring task reminders (habits at scheduled times)
4. Morning briefs (at user's morning_brief_time)
5. Evening check-ins (at user's evening_checkin_time)
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, time
from typing import Optional

from ...logging_config import logger
from ..database import (
    get_database_client_v2,
    Task, TaskStatus, TaskAccountability,
    RecurringTask, RecurringTaskStatus,
    TaskInteraction, InteractionType, InteractionContext,
    Brief, BriefType,
    ScheduledTrigger, TriggerType,
)
from ..whatsapp import get_whatsapp_client


class TaskScheduler:
    """Scheduler that polls every minute for pending actions."""

    POLL_INTERVAL = 60  # seconds

    def __init__(self):
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self.db = None
        self.whatsapp = None

    async def start(self):
        """Start the scheduler."""
        if self._running:
            return

        self._running = True
        self.db = get_database_client_v2()
        self.whatsapp = get_whatsapp_client()

        self._task = asyncio.create_task(self._poll_loop())
        logger.info("Task scheduler started (polling every 60s)")

    async def stop(self):
        """Stop the scheduler."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Task scheduler stopped")

    async def _poll_loop(self):
        """Main polling loop."""
        while self._running:
            try:
                await self._process_due_items()
            except Exception as e:
                logger.error(f"Task scheduler error: {e}")

            await asyncio.sleep(self.POLL_INTERVAL)

    async def _process_due_items(self):
        """Process all due items in this poll cycle."""
        now = datetime.utcnow()
        ist_now = now + timedelta(hours=5, minutes=30)  # Convert to IST

        # 1. Process due task reminders
        await self._process_task_reminders(now)

        # 2. Process due scheduled triggers (check-ins, etc.)
        await self._process_scheduled_triggers(now)

        # 3. Process recurring task reminders
        await self._process_recurring_reminders(ist_now)

        # 4. Process morning briefs (check if it's morning brief time for any user)
        await self._process_morning_briefs(ist_now)

        # 5. Process evening check-ins
        await self._process_evening_checkins(ist_now)

    # ============================================
    # TASK REMINDERS
    # ============================================

    async def _process_task_reminders(self, now: datetime):
        """Send reminders for tasks where remind_at has passed."""
        try:
            due_tasks = await self.db.get_due_tasks(now)

            for task in due_tasks:
                await self._send_task_reminder(task)

        except Exception as e:
            logger.error(f"Error processing task reminders: {e}")

    async def _send_task_reminder(self, task: Task):
        """Send a single task reminder."""
        if not self.whatsapp:
            logger.warning("WhatsApp not configured - skipping task reminder")
            return

        # Anti-spam check
        if not await self._should_send(task.user_phone):
            return

        # Build message
        accountability = task.accountability or TaskAccountability()
        reminder_count = accountability.reminder_count

        messages = [
            f"📝 {task.title}",
            f"Hey, remember this? {task.title}",
            f"{task.title} - you wanted to do this, right?",
            f"Gentle nudge: {task.title}",
        ]
        message = messages[min(reminder_count, len(messages) - 1)]

        # Send
        await self.whatsapp.send_text(task.user_phone, message)
        logger.info(f"Task reminder sent: {task.title} to {task.user_phone}")

        # Update task
        new_accountability = {
            "reminder_count": reminder_count + 1,
            "snooze_count": accountability.snooze_count,
            "escalation_stage": accountability.escalation_stage,
            "last_interaction_at": datetime.utcnow().isoformat(),
        }
        await self.db.update_task(task.id, {
            "status": "reminded",
            "accountability": new_accountability,
        })

        # Log interaction
        await self.db.log_interaction(TaskInteraction(
            user_phone=task.user_phone,
            task_id=task.id,
            type=InteractionType.REMINDED,
            donna_message=message,
            context=InteractionContext.SCHEDULED,
        ))

        # Schedule check-in for 4-6 hours later
        checkin_time = datetime.utcnow() + timedelta(hours=5)
        await self.db.create_trigger(ScheduledTrigger(
            user_phone=task.user_phone,
            trigger_type=TriggerType.TASK_CHECKIN,
            task_id=task.id,
            trigger_at=checkin_time,
        ))

    # ============================================
    # SCHEDULED TRIGGERS (CHECK-INS)
    # ============================================

    async def _process_scheduled_triggers(self, now: datetime):
        """Process scheduled triggers (check-ins, etc.)."""
        try:
            triggers = await self.db.get_pending_triggers(now)

            for trigger in triggers:
                await self._process_trigger(trigger)
                await self.db.mark_trigger_done(trigger.id)

        except Exception as e:
            logger.error(f"Error processing scheduled triggers: {e}")

    async def _process_trigger(self, trigger: ScheduledTrigger):
        """Process a single scheduled trigger."""
        if trigger.trigger_type == TriggerType.TASK_CHECKIN:
            await self._send_task_checkin(trigger)
        elif trigger.trigger_type == TriggerType.RECURRING_REMINDER:
            await self._send_recurring_reminder(trigger)
        # Add more trigger types as needed

    async def _send_task_checkin(self, trigger: ScheduledTrigger):
        """Send a task check-in."""
        if not self.whatsapp or not trigger.task_id:
            return

        task = await self.db.get_task(trigger.task_id)
        if not task or task.status in [TaskStatus.COMPLETED, TaskStatus.DROPPED]:
            return

        if not await self._should_send(trigger.user_phone):
            return

        # Build check-in message with escalating sass
        accountability = task.accountability or TaskAccountability()
        snooze_count = accountability.snooze_count

        if snooze_count == 0:
            message = f"Did you get to \"{task.title}\"?"
        elif snooze_count == 1:
            message = f"So... {task.title}. Still on the list?"
        elif snooze_count == 2:
            message = f"Third time asking about \"{task.title}\". No judgment. Okay, maybe a little."
        else:
            message = f"Okay, real talk: \"{task.title}\" - should I just drop this? Say 'drop' or let's get it done."

        await self.whatsapp.send_text(trigger.user_phone, message)
        logger.info(f"Task check-in sent: {task.title} to {trigger.user_phone}")

        # Log interaction
        await self.db.log_interaction(TaskInteraction(
            user_phone=trigger.user_phone,
            task_id=task.id,
            type=InteractionType.CHECKIN,
            donna_message=message,
            context=InteractionContext.SCHEDULED,
        ))

    # ============================================
    # RECURRING TASK REMINDERS
    # ============================================

    async def _process_recurring_reminders(self, ist_now: datetime):
        """Process recurring task reminders."""
        try:
            # Get current time in HH:MM format
            current_time = ist_now.strftime("%H:%M")
            current_day = ist_now.isoweekday()  # 1=Mon, 7=Sun

            # Get all active recurring tasks
            # We need to check each user's recurring tasks
            # For now, we'll query all and filter
            # TODO: Optimize with a proper query

            # This is a simplified version - in production,
            # we'd want to query only tasks that are due now
            pass  # Implemented via scheduled_triggers instead

        except Exception as e:
            logger.error(f"Error processing recurring reminders: {e}")

    async def _send_recurring_reminder(self, trigger: ScheduledTrigger):
        """Send a recurring task reminder."""
        if not self.whatsapp or not trigger.recurring_task_id:
            return

        task = await self.db.get_recurring_task(trigger.recurring_task_id)
        if not task or task.status != RecurringTaskStatus.ACTIVE:
            return

        if not await self._should_send(trigger.user_phone):
            return

        # Build message with streak
        streak = task.streak_current
        if streak > 0:
            message = f"💪 {task.title} (Day {streak} streak!)"
        else:
            message = f"⏰ {task.title}"

        if task.metric:
            message += f"\nReply with your {task.metric.unit} when done!"

        await self.whatsapp.send_text(trigger.user_phone, message)
        logger.info(f"Recurring reminder sent: {task.title} to {trigger.user_phone}")

        # Log interaction
        await self.db.log_interaction(TaskInteraction(
            user_phone=trigger.user_phone,
            recurring_task_id=task.id,
            type=InteractionType.REMINDED,
            donna_message=message,
            context=InteractionContext.SCHEDULED,
        ))

    # ============================================
    # MORNING BRIEFS
    # ============================================

    async def _process_morning_briefs(self, ist_now: datetime):
        """Send morning briefs at each user's preferred time."""
        try:
            current_time = ist_now.strftime("%H:%M")

            # Check if it's a common morning time (8:00, 8:30, 9:00)
            # In production, we'd query users with this morning_brief_time
            common_times = ["08:00", "08:30", "09:00"]

            if current_time not in common_times:
                return

            # Query users with this morning brief time
            # For now, we'll use the donna_users table
            # TODO: Query users where preferences->>'morning_brief_time' = current_time

            # Simplified: Check if we already sent brief today
            # This would need a proper implementation

        except Exception as e:
            logger.error(f"Error processing morning briefs: {e}")

    async def send_morning_brief(self, phone: str):
        """Send morning brief to a specific user."""
        if not self.whatsapp:
            return

        if not await self._should_send(phone, is_brief=True):
            return

        # Get pending tasks
        pending_tasks = await self.db.get_pending_tasks(phone)

        # Get active habits
        recurring_tasks = await self.db.get_active_recurring_tasks(phone)

        # Build brief
        lines = ["☀️ *Good morning!* Here's your day:\n"]

        if pending_tasks:
            lines.append("📋 *Tasks:*")
            for task in pending_tasks[:5]:
                priority_emoji = "🔴" if task.priority <= 2 else "🟡" if task.priority == 3 else "⚪"
                lines.append(f"  {priority_emoji} {task.title}")
            if len(pending_tasks) > 5:
                lines.append(f"  ... and {len(pending_tasks) - 5} more")
            lines.append("")

        if recurring_tasks:
            lines.append("🔄 *Habits:*")
            for habit in recurring_tasks[:5]:
                streak_text = f" (🔥 {habit.streak_current})" if habit.streak_current > 0 else ""
                lines.append(f"  • {habit.title}{streak_text}")
            lines.append("")

        if not pending_tasks and not recurring_tasks:
            lines.append("Looks like a light day! Enjoy it. 🌟")
        else:
            lines.append("Let's make it a great day! 💪")

        message = "\n".join(lines)

        await self.whatsapp.send_text(phone, message)
        logger.info(f"Morning brief sent to {phone}")

        # Save brief record
        await self.db.save_brief(Brief(
            user_phone=phone,
            type=BriefType.MORNING,
            task_ids=[t.id for t in pending_tasks[:5]],
            recurring_task_ids=[t.id for t in recurring_tasks[:5]],
            content_summary=f"{len(pending_tasks)} tasks, {len(recurring_tasks)} habits",
        ))

    # ============================================
    # EVENING CHECK-INS
    # ============================================

    async def _process_evening_checkins(self, ist_now: datetime):
        """Send evening check-ins at each user's preferred time."""
        try:
            current_time = ist_now.strftime("%H:%M")

            # Check common evening times
            common_times = ["18:00", "18:30", "19:00", "20:00"]

            if current_time not in common_times:
                return

            # Similar to morning briefs - would query users with this evening time

        except Exception as e:
            logger.error(f"Error processing evening check-ins: {e}")

    async def send_evening_checkin(self, phone: str):
        """Send evening check-in to a specific user."""
        if not self.whatsapp:
            return

        if not await self._should_send(phone, is_brief=True):
            return

        # Get tasks that were reminded today but not completed
        pending_tasks = await self.db.get_tasks(phone, status=TaskStatus.REMINDED)

        if not pending_tasks:
            message = "🌙 Great work today! All tasks handled. Rest well!"
        elif len(pending_tasks) == 1:
            task = pending_tasks[0]
            message = f"🌙 End of day check-in:\n\nDid you finish \"{task.title}\"?\n\nReply 'done' or I'll roll it to tomorrow."
        else:
            lines = ["🌙 End of day check-in:\n"]
            lines.append("Still open:")
            for task in pending_tasks[:3]:
                lines.append(f"  • {task.title}")
            lines.append("\nReply 'done [task]' for any you completed, or I'll roll them to tomorrow.")
            message = "\n".join(lines)

        await self.whatsapp.send_text(phone, message)
        logger.info(f"Evening check-in sent to {phone}")

        # Save brief record
        await self.db.save_brief(Brief(
            user_phone=phone,
            type=BriefType.EVENING,
            task_ids=[t.id for t in pending_tasks],
            content_summary=f"{len(pending_tasks)} pending tasks",
        ))

    # ============================================
    # ANTI-SPAM
    # ============================================

    async def _should_send(self, phone: str, is_brief: bool = False) -> bool:
        """Check if we should send a message (anti-spam)."""
        try:
            recent = await self.db.get_recent_interactions(phone, hours=24)

            # Count task-related outgoing messages in last 24h
            outgoing_count = len([
                r for r in recent
                if r.type in [InteractionType.REMINDED, InteractionType.CHECKIN]
            ])

            # Max 8 task-related messages per day (briefs don't count toward this)
            if not is_brief and outgoing_count >= 8:
                logger.warning(f"Anti-spam: {phone} has {outgoing_count} messages today")
                return False

            # Don't send reminders within 1 hour of each other (briefs exempt)
            if not is_brief and recent:
                last_reminder = next(
                    (r for r in recent if r.type == InteractionType.REMINDED),
                    None
                )
                if last_reminder and last_reminder.timestamp:
                    try:
                        ts = str(last_reminder.timestamp).replace('Z', '').split('+')[0]
                        last_time = datetime.fromisoformat(ts)
                        time_since = datetime.utcnow() - last_time
                        if time_since.total_seconds() < 3600:
                            logger.debug(f"Anti-spam: Last reminder was {time_since.seconds}s ago")
                            return False
                    except Exception:
                        pass

            return True

        except Exception as e:
            logger.error(f"Anti-spam check failed: {e}")
            return True  # Allow on error


# Singleton
_task_scheduler: Optional[TaskScheduler] = None


def get_task_scheduler() -> TaskScheduler:
    """Get the singleton task scheduler."""
    global _task_scheduler
    if _task_scheduler is None:
        _task_scheduler = TaskScheduler()
    return _task_scheduler


async def start_task_scheduler():
    """Start the task scheduler."""
    scheduler = get_task_scheduler()
    await scheduler.start()


async def stop_task_scheduler():
    """Stop the task scheduler."""
    scheduler = get_task_scheduler()
    await scheduler.stop()


__all__ = ["TaskScheduler", "get_task_scheduler", "start_task_scheduler", "stop_task_scheduler"]
