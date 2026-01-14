"""Webhook endpoints for scheduled triggers.

These endpoints are called by Nhost scheduled events to:
- Send task reminders
- Send check-ins
- Send morning/evening briefs
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel

from ..logging_config import logger
from ..services.database import (
    get_database_client_v2,
    Task, TaskStatus, TaskAccountability,
    RecurringTask,
    TaskInteraction, InteractionType, InteractionContext,
    Brief, BriefType,
    ScheduledTrigger, TriggerType,
)
from ..services.whatsapp import get_whatsapp_client
from ..services.calendar import get_calendar_client


router = APIRouter(prefix="/triggers", tags=["triggers"])


# ============================================
# REQUEST MODELS
# ============================================

class TriggerRequest(BaseModel):
    """Request for trigger webhook."""
    trigger_id: Optional[str] = None
    task_id: Optional[str] = None
    recurring_task_id: Optional[str] = None
    user_phone: str
    trigger_type: str  # task_reminder, task_checkin, recurring_reminder, morning_brief, evening_checkin


class BriefRequest(BaseModel):
    """Request for brief webhook."""
    user_phone: str
    brief_type: str = "morning"  # morning, evening, weekly


# ============================================
# ANTI-SPAM LOGIC
# ============================================

async def should_send_message(phone: str, message_type: str) -> bool:
    """Check if we should send a message (anti-spam)."""
    db = get_database_client_v2()

    try:
        recent = await db.get_recent_interactions(phone, hours=24)

        # Count task-related outgoing messages in last 24h
        outgoing_count = len([
            r for r in recent
            if r.type in [InteractionType.REMINDED, InteractionType.CHECKIN]
        ])

        # Max 8 task-related messages per day
        if outgoing_count >= 8:
            logger.warning(f"Anti-spam: {phone} has {outgoing_count} messages today, skipping")
            return False

        # Don't send within 1 hour of last reminder (except briefs)
        if message_type != "brief" and recent:
            last_reminder = next(
                (r for r in recent if r.type == InteractionType.REMINDED),
                None
            )
            if last_reminder and last_reminder.timestamp:
                time_since = datetime.utcnow() - datetime.fromisoformat(
                    str(last_reminder.timestamp).replace('Z', '+00:00').replace('+00:00', '')
                )
                if time_since.total_seconds() < 3600:  # 1 hour
                    logger.info(f"Anti-spam: Last reminder was {time_since.seconds}s ago, skipping")
                    return False

        return True
    except Exception as e:
        logger.error(f"Anti-spam check failed: {e}")
        return True  # Allow on error


# ============================================
# TASK REMINDER
# ============================================

@router.post("/task/reminder")
async def task_reminder(request: TriggerRequest, background_tasks: BackgroundTasks):
    """Send a task reminder."""
    logger.info(f"Task reminder trigger: {request.task_id} for {request.user_phone}")

    db = get_database_client_v2()
    whatsapp = get_whatsapp_client()

    if not whatsapp:
        raise HTTPException(status_code=500, detail="WhatsApp not configured")

    # Get task
    task = await db.get_task(request.task_id)
    if not task:
        return {"ok": False, "error": "Task not found"}

    if task.status != TaskStatus.PENDING:
        return {"ok": False, "error": f"Task status is {task.status}"}

    # Anti-spam check
    if not await should_send_message(request.user_phone, "reminder"):
        return {"ok": False, "error": "Anti-spam: too many messages"}

    # Build reminder message (Donna style)
    messages = [
        f"📝 {task.title}",
        f"Hey, remember this? {task.title}",
        f"{task.title} - you wanted to do this, right?",
        f"Gentle nudge: {task.title}",
    ]

    # Pick message based on reminder count
    accountability = task.accountability or TaskAccountability()
    reminder_count = accountability.reminder_count
    message_idx = min(reminder_count, len(messages) - 1)
    message = messages[message_idx]

    # Send WhatsApp
    await whatsapp.send_text(request.user_phone, message)

    # Update task accountability
    new_accountability = {
        "reminder_count": reminder_count + 1,
        "snooze_count": accountability.snooze_count,
        "escalation_stage": accountability.escalation_stage,
        "last_interaction_at": datetime.utcnow().isoformat(),
    }
    await db.update_task(task.id, {
        "status": "reminded",
        "accountability": new_accountability,
    })

    # Log interaction
    await db.log_interaction(TaskInteraction(
        user_phone=request.user_phone,
        task_id=task.id,
        type=InteractionType.REMINDED,
        donna_message=message,
        context=InteractionContext.SCHEDULED,
    ))

    # Schedule check-in for later (4-6 hours)
    checkin_time = datetime.utcnow() + timedelta(hours=5)
    await db.create_trigger(ScheduledTrigger(
        user_phone=request.user_phone,
        trigger_type=TriggerType.TASK_CHECKIN,
        task_id=task.id,
        trigger_at=checkin_time,
    ))

    logger.info(f"Task reminder sent: {task.title} to {request.user_phone}")
    return {"ok": True, "message": message}


# ============================================
# TASK CHECK-IN
# ============================================

@router.post("/task/checkin")
async def task_checkin(request: TriggerRequest, background_tasks: BackgroundTasks):
    """Check in on a task - "Did you do X?"."""
    logger.info(f"Task check-in trigger: {request.task_id} for {request.user_phone}")

    db = get_database_client_v2()
    whatsapp = get_whatsapp_client()

    if not whatsapp:
        raise HTTPException(status_code=500, detail="WhatsApp not configured")

    # Get task
    task = await db.get_task(request.task_id)
    if not task:
        return {"ok": False, "error": "Task not found"}

    # Skip if already completed
    if task.status == TaskStatus.COMPLETED:
        return {"ok": False, "error": "Task already completed"}

    if task.status == TaskStatus.DROPPED:
        return {"ok": False, "error": "Task was dropped"}

    # Anti-spam check
    if not await should_send_message(request.user_phone, "checkin"):
        return {"ok": False, "error": "Anti-spam: too many messages"}

    # Build check-in message (escalating sass)
    accountability = task.accountability or TaskAccountability()
    snooze_count = accountability.snooze_count

    if snooze_count == 0:
        message = f"Did you get to \"{task.title}\"?"
    elif snooze_count == 1:
        message = f"So... {task.title}. Still on the list?"
    elif snooze_count == 2:
        message = f"Third time asking about \"{task.title}\". No judgment. Okay, maybe a little."
    elif snooze_count >= 3:
        message = f"Okay, real talk: \"{task.title}\" - should I just drop this? Say 'drop' or let's get it done."

    # Send WhatsApp
    await whatsapp.send_text(request.user_phone, message)

    # Log interaction
    await db.log_interaction(TaskInteraction(
        user_phone=request.user_phone,
        task_id=task.id,
        type=InteractionType.CHECKIN,
        donna_message=message,
        context=InteractionContext.SCHEDULED,
    ))

    logger.info(f"Task check-in sent: {task.title} to {request.user_phone}")
    return {"ok": True, "message": message}


# ============================================
# RECURRING TASK REMINDER
# ============================================

@router.post("/recurring/reminder")
async def recurring_reminder(request: TriggerRequest, background_tasks: BackgroundTasks):
    """Send a recurring task reminder (habit)."""
    logger.info(f"Recurring reminder trigger: {request.recurring_task_id} for {request.user_phone}")

    db = get_database_client_v2()
    whatsapp = get_whatsapp_client()

    if not whatsapp:
        raise HTTPException(status_code=500, detail="WhatsApp not configured")

    # Get recurring task
    task = await db.get_recurring_task(request.recurring_task_id)
    if not task:
        return {"ok": False, "error": "Recurring task not found"}

    if task.status != "active":
        return {"ok": False, "error": f"Task status is {task.status}"}

    # Build message with streak info
    streak = task.streak_current
    if streak > 0:
        message = f"💪 {task.title} (Day {streak} streak!)"
    else:
        message = f"⏰ {task.title}"

    # Add metric prompt if applicable
    if task.metric:
        message += f"\nReply with your {task.metric.unit} when done!"

    # Send WhatsApp
    await whatsapp.send_text(request.user_phone, message)

    # Log interaction
    await db.log_interaction(TaskInteraction(
        user_phone=request.user_phone,
        recurring_task_id=task.id,
        type=InteractionType.REMINDED,
        donna_message=message,
        context=InteractionContext.SCHEDULED,
    ))

    logger.info(f"Recurring reminder sent: {task.title} to {request.user_phone}")
    return {"ok": True, "message": message}


# ============================================
# MORNING BRIEF
# ============================================

@router.post("/brief/morning")
async def morning_brief(request: BriefRequest, background_tasks: BackgroundTasks):
    """Send morning brief - calendar, tasks, habits."""
    logger.info(f"Morning brief trigger for {request.user_phone}")

    db = get_database_client_v2()
    whatsapp = get_whatsapp_client()
    calendar = get_calendar_client()

    if not whatsapp:
        raise HTTPException(status_code=500, detail="WhatsApp not configured")

    # Get pending tasks
    pending_tasks = await db.get_pending_tasks(request.user_phone)

    # Get active recurring tasks
    recurring_tasks = await db.get_active_recurring_tasks(request.user_phone)

    # Get today's calendar events
    calendar_events = []
    if calendar:
        try:
            today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
            today_end = today_start + timedelta(days=1)
            calendar_events = await calendar.list_events(time_min=today_start, time_max=today_end, max_results=5)
        except Exception as e:
            logger.warning(f"Failed to get calendar events: {e}")

    # Build brief
    lines = ["☀️ *Good morning!* Here's your day:\n"]

    # Calendar events for today
    if calendar_events:
        lines.append("📅 *Today's Schedule:*")
        for event in calendar_events[:4]:  # Max 4 events
            # Format time
            start_str = event.get("start", "")
            if "T" in str(start_str):
                try:
                    start_dt = datetime.fromisoformat(str(start_str).replace("Z", "+00:00"))
                    # Convert to IST
                    ist_time = start_dt + timedelta(hours=5, minutes=30)
                    time_text = ist_time.strftime("%I:%M %p").lstrip("0")
                except:
                    time_text = "All day"
            else:
                time_text = "All day"
            lines.append(f"  • {time_text} - {event.get('summary', 'No title')}")
        if len(calendar_events) > 4:
            lines.append(f"  ... and {len(calendar_events) - 4} more")
        lines.append("")

    # Tasks for today (filter for today's reminders)
    today_tasks = []
    for task in pending_tasks:
        if task.remind_at:
            remind_date = task.remind_at.date() if hasattr(task.remind_at, 'date') else None
            today = (datetime.utcnow() + timedelta(hours=5, minutes=30)).date()
            if remind_date == today:
                today_tasks.append(task)

    if today_tasks:
        lines.append("📋 *Tasks:*")
        for task in today_tasks[:5]:  # Max 5 tasks
            priority_emoji = "🔴" if task.priority <= 2 else "🟡" if task.priority == 3 else "⚪"
            lines.append(f"  {priority_emoji} {task.title}")
        if len(today_tasks) > 5:
            lines.append(f"  ... and {len(today_tasks) - 5} more")
        lines.append("")
    elif pending_tasks:
        # Show upcoming tasks if none for today
        lines.append("📋 *Upcoming:*")
        for task in pending_tasks[:3]:
            lines.append(f"  • {task.title}")
        lines.append("")

    # Habits for today
    if recurring_tasks:
        lines.append("🔄 *Habits:*")
        for habit in recurring_tasks[:5]:
            streak_text = f" (🔥 {habit.streak_current})" if habit.streak_current > 0 else ""
            lines.append(f"  • {habit.title}{streak_text}")
        lines.append("")

    # Closing
    total_items = len(calendar_events) + len(today_tasks or pending_tasks) + len(recurring_tasks)
    if total_items == 0:
        lines.append("Looks like a light day! Enjoy it. 🌟")
    else:
        closings = [
            "Let's make it a great day! 💪",
            "You've got this. 💪",
            "Make it count!",
            "Time to crush it.",
        ]
        import random
        lines.append(random.choice(closings))

    message = "\n".join(lines)

    # Send WhatsApp
    await whatsapp.send_text(request.user_phone, message)

    # Save brief record
    await db.save_brief(Brief(
        user_phone=request.user_phone,
        type=BriefType.MORNING,
        task_ids=[t.id for t in (today_tasks or pending_tasks)[:5]],
        recurring_task_ids=[t.id for t in recurring_tasks[:5]],
        content_summary=f"{len(calendar_events)} events, {len(today_tasks or pending_tasks)} tasks, {len(recurring_tasks)} habits",
    ))

    logger.info(f"Morning brief sent to {request.user_phone}")
    return {"ok": True, "message": message}


# ============================================
# EVENING CHECK-IN
# ============================================

@router.post("/brief/evening")
async def evening_checkin(request: BriefRequest, background_tasks: BackgroundTasks):
    """Send evening check-in - what got done today?"""
    logger.info(f"Evening check-in trigger for {request.user_phone}")

    db = get_database_client_v2()
    whatsapp = get_whatsapp_client()

    if not whatsapp:
        raise HTTPException(status_code=500, detail="WhatsApp not configured")

    # Get tasks that were reminded today but not completed
    pending_tasks = await db.get_tasks(request.user_phone, status=TaskStatus.REMINDED)
    pending_pending = await db.get_tasks(request.user_phone, status=TaskStatus.PENDING)

    # Get today's habit completions
    recurring_tasks = await db.get_active_recurring_tasks(request.user_phone)

    # Build evening summary
    lines = ["🌙 *End of day check-in*\n"]

    # Tasks status
    open_tasks = pending_tasks + [t for t in pending_pending if t.remind_at and t.remind_at.date() == (datetime.utcnow() + timedelta(hours=5, minutes=30)).date()]

    if not open_tasks:
        lines.append("✅ All tasks handled today! Nice work.")
    elif len(open_tasks) == 1:
        task = open_tasks[0]
        lines.append(f"📋 Still open: *{task.title}*")
        lines.append("Reply 'done' or I'll roll it to tomorrow.")
    else:
        lines.append("📋 *Still open:*")
        for task in open_tasks[:4]:
            lines.append(f"  • {task.title}")
        if len(open_tasks) > 4:
            lines.append(f"  ... and {len(open_tasks) - 4} more")
        lines.append("\nReply 'done [task]' for any completed.")

    lines.append("")

    # Habit summary
    if recurring_tasks:
        # Count habits with streaks (maintained today)
        active_streaks = [h for h in recurring_tasks if h.streak_current > 0]
        if active_streaks:
            total_streak = sum(h.streak_current for h in active_streaks)
            lines.append(f"🔥 {len(active_streaks)} habit streaks going ({total_streak} total days)")

    # Closing
    if not open_tasks and active_streaks if recurring_tasks else False:
        lines.append("\nCrushed it today. Rest well! 💤")
    elif not open_tasks:
        lines.append("\nGood day. See you tomorrow! 💤")
    else:
        lines.append("\nNo worries on what's left - tomorrow's a new day. 💤")

    message = "\n".join(lines)

    # Send WhatsApp
    await whatsapp.send_text(request.user_phone, message)

    # Save brief record
    await db.save_brief(Brief(
        user_phone=request.user_phone,
        type=BriefType.EVENING,
        task_ids=[t.id for t in open_tasks],
        recurring_task_ids=[t.id for t in recurring_tasks] if recurring_tasks else [],
        content_summary=f"{len(open_tasks)} open tasks, {len(recurring_tasks)} habits",
    ))

    logger.info(f"Evening check-in sent to {request.user_phone}")
    return {"ok": True, "message": message}


# ============================================
# GENERIC TRIGGER PROCESSOR
# ============================================

@router.post("/process")
async def process_trigger(request: TriggerRequest, background_tasks: BackgroundTasks):
    """Process any scheduled trigger."""
    logger.info(f"Processing trigger: {request.trigger_type} for {request.user_phone}")

    if request.trigger_type == "task_reminder":
        return await task_reminder(request, background_tasks)
    elif request.trigger_type == "task_checkin":
        return await task_checkin(request, background_tasks)
    elif request.trigger_type == "recurring_reminder":
        return await recurring_reminder(request, background_tasks)
    elif request.trigger_type == "morning_brief":
        return await morning_brief(
            BriefRequest(user_phone=request.user_phone, brief_type="morning"),
            background_tasks
        )
    elif request.trigger_type == "evening_checkin":
        return await evening_checkin(
            BriefRequest(user_phone=request.user_phone, brief_type="evening"),
            background_tasks
        )
    else:
        raise HTTPException(status_code=400, detail=f"Unknown trigger type: {request.trigger_type}")


# ============================================
# MANUAL TESTING ENDPOINTS
# ============================================

@router.post("/test/morning-brief/{phone}")
async def test_morning_brief(phone: str, background_tasks: BackgroundTasks):
    """Test endpoint to send morning brief manually."""
    return await morning_brief(
        BriefRequest(user_phone=phone, brief_type="morning"),
        background_tasks
    )


@router.post("/test/evening-checkin/{phone}")
async def test_evening_checkin(phone: str, background_tasks: BackgroundTasks):
    """Test endpoint to send evening check-in manually."""
    return await evening_checkin(
        BriefRequest(user_phone=phone, brief_type="evening"),
        background_tasks
    )


__all__ = ["router"]
