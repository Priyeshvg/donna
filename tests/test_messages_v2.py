#!/usr/bin/env python3
"""
Standalone test script for Donna AI v2
Generates 20 random test messages to verify tool detection and smart defaults

Run: python3 tests/test_messages_v2.py
"""

import random
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional

# =============================================================================
# TEST DATA
# =============================================================================

def generate_random_phone() -> str:
    """Generate random Indian phone number."""
    return f"+91{''.join([str(random.randint(0, 9)) for _ in range(10)])}"


# All test messages grouped by category
TEST_MESSAGES: List[Tuple[str, str, Dict]] = [
    # -------------------------------------------------------------------------
    # TASK CREATION (one-time) - should use create_task
    # -------------------------------------------------------------------------
    ("remind me to call mom tomorrow", "create_task", {"smart_default": "10am (call)"}),
    ("set a reminder for dentist appointment at 3pm friday", "create_task", {"has_time": True}),
    ("remind me to send invoice on monday", "create_task", {"smart_default": "10am (send)"}),
    ("don't let me forget to buy groceries", "create_task", {"smart_default": "9am"}),
    ("remind me to take medicine at 9pm", "create_task", {"has_time": True}),
    ("book flight tickets by next week", "create_task", {"has_due_date": True}),
    ("reminder to pay electricity bill", "create_task", {"smart_default": "9am"}),
    ("remind me about the meeting at 2pm", "create_task", {"has_time": True}),

    # -------------------------------------------------------------------------
    # RECURRING TASKS / HABITS - should use create_recurring_task
    # -------------------------------------------------------------------------
    ("I want to drink more water", "create_recurring_task", {
        "detected_pattern": "water", "times_per_day": 4, "metric": "glasses"
    }),
    ("help me build a gym habit", "create_recurring_task", {
        "detected_pattern": "gym", "times_per_day": 1, "metric": "minutes"
    }),
    ("remind me to read every night", "create_recurring_task", {
        "detected_pattern": "read", "times_per_day": 1, "reminder_time": "21:00"
    }),
    ("I want to meditate daily", "create_recurring_task", {
        "detected_pattern": "meditate", "times_per_day": 1, "reminder_time": "07:30"
    }),
    ("track my water intake", "create_recurring_task", {
        "detected_pattern": "water", "metric": "glasses"
    }),
    ("i want to walk 10000 steps every day", "create_recurring_task", {
        "detected_pattern": "walk", "metric": "steps"
    }),
    ("help me journal before bed", "create_recurring_task", {
        "detected_pattern": "journal", "reminder_time": "21:30"
    }),

    # -------------------------------------------------------------------------
    # TASK COMPLETION - should use complete_task
    # -------------------------------------------------------------------------
    ("done with the call", "complete_task", {"search": "call"}),
    ("finished my workout", "complete_task", {"search": "workout"}),
    ("I drank water", "complete_task", {"search": "water", "type": "habit"}),
    ("completed reading", "complete_task", {"search": "reading"}),
    ("done", "complete_task", {"search": "most_recent"}),
    ("finished the dentist appointment", "complete_task", {"search": "dentist"}),
    ("workout done!", "complete_task", {"search": "workout"}),

    # -------------------------------------------------------------------------
    # SNOOZE - should use snooze_task
    # -------------------------------------------------------------------------
    ("not now, remind me later", "snooze_task", {"hours": 5}),
    ("snooze for 2 hours", "snooze_task", {"hours": 2}),
    ("later", "snooze_task", {"hours": 5}),
    ("remind me in an hour", "snooze_task", {"hours": 1}),
    ("not right now", "snooze_task", {"hours": 5}),

    # -------------------------------------------------------------------------
    # DROP TASK - should use drop_task
    # -------------------------------------------------------------------------
    ("forget about the dentist", "drop_task", {"search": "dentist"}),
    ("cancel the grocery reminder", "drop_task", {"search": "grocery"}),
    ("drop the call reminder", "drop_task", {"search": "call"}),
    ("nevermind the invoice", "drop_task", {"search": "invoice"}),

    # -------------------------------------------------------------------------
    # SEARCH/LIST TASKS - should use search_tasks
    # -------------------------------------------------------------------------
    ("what's on my list?", "search_tasks", {"query": ""}),
    ("show my habits", "search_tasks", {"include_habits": True}),
    ("what do I have pending?", "search_tasks", {"query": ""}),
    ("list all my reminders", "search_tasks", {"query": ""}),
    ("what tasks do I have today?", "search_tasks", {"query": "today"}),

    # -------------------------------------------------------------------------
    # MEMORY STORE - should use store_memory
    # -------------------------------------------------------------------------
    ("remember that Akash's birthday is on March 15", "store_memory", {"entity": "Akash", "category": "event"}),
    ("my wife's name is Priya", "store_memory", {"entity": "wife", "category": "relationship"}),
    ("I prefer morning meetings", "store_memory", {"category": "preference"}),
    ("Rahul's phone number is 9876543210", "store_memory", {"entity": "Rahul", "category": "contact"}),
    ("mom's anniversary is december 5", "store_memory", {"entity": "mom", "category": "event"}),

    # -------------------------------------------------------------------------
    # MEMORY SEARCH - should use search_memory
    # -------------------------------------------------------------------------
    ("when is Akash's birthday?", "search_memory", {"query": "Akash birthday"}),
    ("what do you know about me?", "search_memory", {"query": "preferences"}),
    ("what's Rahul's number?", "search_memory", {"query": "Rahul phone"}),

    # -------------------------------------------------------------------------
    # USER UPDATE - should use update_user
    # -------------------------------------------------------------------------
    ("my name is Priyesh", "update_user", {"name": "Priyesh"}),
    ("call me Raj", "update_user", {"name": "Raj"}),
    ("change my morning brief to 7am", "update_user", {"morning_brief_time": "07:00"}),

    # -------------------------------------------------------------------------
    # CALENDAR - should use calendar tools
    # -------------------------------------------------------------------------
    ("what's on my calendar today?", "list_calendar_events", {"days": 1}),
    ("show my schedule for this week", "list_calendar_events", {"days": 7}),
    ("find me a free slot tomorrow", "find_free_time", {"days": 1}),
    ("when am I free this week?", "find_free_time", {"days": 7}),

    # -------------------------------------------------------------------------
    # GENERAL CHAT - should use send_whatsapp
    # -------------------------------------------------------------------------
    ("hey donna", "send_whatsapp", {"type": "greeting"}),
    ("good morning", "send_whatsapp", {"type": "greeting"}),
    ("thanks!", "send_whatsapp", {"type": "gratitude"}),
    ("how are you?", "send_whatsapp", {"type": "chat"}),
    ("who are you?", "send_whatsapp", {"type": "intro"}),
    ("what can you do?", "send_whatsapp", {"type": "help"}),
]


# =============================================================================
# SMART DEFAULT DETECTION
# =============================================================================

def detect_smart_defaults(title: str) -> Dict:
    """Detect smart default time based on task type."""
    title_lower = title.lower()

    # Morning activities
    if any(word in title_lower for word in ["exercise", "gym", "workout", "run", "yoga", "meditate", "meditation"]):
        return {"time": "07:00", "reason": "morning activity"}

    # Business hour activities
    if any(word in title_lower for word in ["call", "phone", "meeting", "email", "send"]):
        return {"time": "10:00", "reason": "business hours"}

    # Evening activities
    if any(word in title_lower for word in ["read", "reading", "book", "journal"]):
        return {"time": "21:00", "reason": "evening activity"}

    # Default
    return {"time": "09:00", "reason": "general default"}


def detect_recurring_pattern(title: str) -> Optional[Dict]:
    """Detect if task should be recurring and return pattern."""
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


def detect_tool(message: str) -> str:
    """Detect which tool should be used for a message."""
    msg = message.lower()

    # Memory store - check first (before other patterns)
    if any(phrase in msg for phrase in [
        "remember that", "my wife", "my husband", "birthday is",
        "'s phone", "'s number", "'s email", "anniversary is",
        "i prefer", "my mom", "my dad"
    ]):
        return "store_memory"

    # Memory search
    if any(phrase in msg for phrase in ["when is", "what do you know", "tell me about"]):
        return "search_memory"
    if "what's" in msg and any(word in msg for word in ["number", "phone", "birthday"]):
        return "search_memory"

    # User update
    if any(phrase in msg for phrase in ["my name is", "call me", "change my morning", "change my evening"]):
        return "update_user"

    # Calendar
    if any(word in msg for word in ["calendar", "schedule"]):
        return "list_calendar_events"
    if any(phrase in msg for phrase in ["free slot", "free time", "when am i free"]):
        return "find_free_time"

    # Completion
    if any(word in msg for word in ["done", "finished", "completed", "did it", "drank"]):
        return "complete_task"

    # Snooze
    if any(phrase in msg for phrase in ["later", "not now", "snooze", "remind me in", "not right now"]):
        return "snooze_task"

    # Drop - be more careful with "forget about" vs "don't forget"
    if any(phrase in msg for phrase in ["forget about", "cancel the", "drop the", "nevermind"]):
        return "drop_task"

    # Search tasks
    if any(phrase in msg for phrase in ["list", "what's on", "show my", "pending", "my tasks", "my habits", "what do i have"]):
        return "search_tasks"

    # Recurring task detection
    if any(word in msg for word in ["habit", "daily", "every day", "every night", "track"]):
        return "create_recurring_task"
    if any(phrase in msg for phrase in ["i want to", "help me"]) and any(word in msg for word in ["water", "gym", "exercise", "meditate", "read", "walk", "journal"]):
        return "create_recurring_task"

    # Task creation - includes "don't forget", "book", etc
    if any(phrase in msg for phrase in ["remind", "reminder", "don't forget", "don't let me forget", "book ", "pay "]):
        return "create_task"

    # Default: chat
    return "send_whatsapp"


# =============================================================================
# TEST RUNNER
# =============================================================================

def run_test(message: str, expected_tool: str, metadata: Dict) -> Tuple[bool, str]:
    """Run a single test and return (passed, details)."""
    detected_tool = detect_tool(message)

    if detected_tool == expected_tool:
        return True, f"Correctly detected: {detected_tool}"
    else:
        return False, f"Expected {expected_tool}, got {detected_tool}"


def main():
    """Run 20 random test messages."""
    print("=" * 70)
    print("DONNA AI v2 - MESSAGE DETECTION TEST")
    print("=" * 70)
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    # Select 20 random messages
    selected = random.sample(TEST_MESSAGES, 20)

    passed = 0
    failed = 0

    for i, (message, expected_tool, metadata) in enumerate(selected, 1):
        phone = generate_random_phone()
        success, details = run_test(message, expected_tool, metadata)

        status = "[PASS]" if success else "[FAIL]"
        if success:
            passed += 1
        else:
            failed += 1

        print(f"\n{status} Test {i}/20")
        print(f"  Phone: {phone}")
        print(f"  Message: \"{message}\"")
        print(f"  {details}")

        # Show smart defaults for task creation
        if expected_tool == "create_task":
            defaults = detect_smart_defaults(message)
            print(f"  Smart default: {defaults['time']} ({defaults['reason']})")

        # Show pattern detection for recurring tasks
        if expected_tool == "create_recurring_task":
            pattern = detect_recurring_pattern(message)
            if pattern:
                print(f"  Pattern: {pattern['frequency']}, {pattern['times_per_day']}x/day")
                if pattern.get('metric'):
                    print(f"  Metric: {pattern['metric']['goal']} {pattern['metric']['unit']}")

    # Summary
    print("\n" + "=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)
    print(f"PASSED: {passed}/20 ({passed/20*100:.0f}%)")
    print(f"FAILED: {failed}/20 ({failed/20*100:.0f}%)")
    print("=" * 70)

    # Show all test categories coverage
    print("\nCOVERAGE BY CATEGORY:")
    categories = {}
    for msg, tool, meta in selected:
        if tool not in categories:
            categories[tool] = 0
        categories[tool] += 1

    for tool, count in sorted(categories.items(), key=lambda x: -x[1]):
        print(f"  {tool}: {count} tests")

    print("\n" + "=" * 70)
    print("SMART DEFAULTS EXAMPLES:")
    print("=" * 70)
    examples = [
        "call mom",
        "gym workout",
        "read a book",
        "buy groceries",
        "send email"
    ]
    for example in examples:
        defaults = detect_smart_defaults(example)
        print(f"  \"{example}\" -> {defaults['time']} ({defaults['reason']})")

    print("\n" + "=" * 70)
    print("RECURRING PATTERN EXAMPLES:")
    print("=" * 70)
    habits = [
        "drink water",
        "go to gym",
        "read before bed",
        "meditate",
        "walk 10000 steps",
        "journal"
    ]
    for habit in habits:
        pattern = detect_recurring_pattern(habit)
        if pattern:
            metric_str = f", tracking {pattern['metric']['unit']}" if pattern.get('metric') else ""
            print(f"  \"{habit}\" -> {pattern['times_per_day']}x/day at {pattern['reminder_times']}{metric_str}")


if __name__ == "__main__":
    main()
