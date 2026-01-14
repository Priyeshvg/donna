#!/usr/bin/env python3
"""
Simulated 40-message conversation with Donna AI
Phone: +91123
This simulates a realistic user journey over a few days
"""

from datetime import datetime

PHONE = "+91123"

# Simulated conversation - alternating User and Donna messages
CONVERSATION = [
    # === DAY 1: Onboarding ===

    # 1-2: First contact
    ("USER", "hey"),
    ("DONNA", "Hey! I'm Donna. Think of me as your personal assistant who actually remembers things and won't let you slack off. What's your name?"),

    # 3-4: Name setup
    ("USER", "I'm Priyesh"),
    ("DONNA", "Got it, Priyesh. Nice to meet you. So what do you need help with? Reminders, building habits, keeping track of things - I do it all."),

    # 5-6: First task
    ("USER", "remind me to call mom tomorrow"),
    ("DONNA", "Done. I'll remind you tomorrow at 10:00 AM.\n\n📝 Call mom\n\nI won't let you forget."),

    # 7-8: Second task with specific time
    ("USER", "also remind me about dentist appointment at 3pm on friday"),
    ("DONNA", "Got it.\n\n📝 Dentist appointment\n📅 Friday, 3:00 PM\n\nI'll ping you before so you're not late."),

    # 9-10: Habit request
    ("USER", "I want to drink more water"),
    ("DONNA", "Smart. I'll remind you 4 times a day - 9am, 12pm, 4pm, and 8pm. That's about 8 glasses if you drink one each time.\n\n🔄 Drink water\n⏰ 4x daily\n📊 Tracking: glasses\n\nLet's build that streak."),

    # 11-12: Another habit
    ("USER", "help me build a gym habit"),
    ("DONNA", "On it. Morning workout reminder set for 7:00 AM daily.\n\n🔄 Gym workout\n⏰ Daily at 7:00 AM\n📊 Tracking: minutes\n🎯 Goal: 30 min\n\nNo excuses. I'll be watching."),

    # 13-14: Memory store
    ("USER", "remember that Akash's birthday is on March 15"),
    ("DONNA", "Stored. Akash's birthday - March 15. I'll remind you a day before so you're not that friend who forgets."),

    # 15-16: List check
    ("USER", "what's on my list?"),
    ("DONNA", "Here's what you've got:\n\n📋 *Tasks:*\n• Call mom (tomorrow 10am)\n• Dentist appointment (Fri 3pm)\n\n🔄 *Habits:*\n• Drink water (4x daily)\n• Gym workout (7am)\n\nTwo tasks, two habits. Let's crush it."),

    # === DAY 2: First reminders ===

    # 17-18: Water reminder (system triggered)
    ("DONNA", "💧 Water check. Have you had a glass yet?"),
    ("USER", "yes just had one"),

    # 19-20: Confirm completion
    ("DONNA", "Nice! That's 1 glass down. 🔥 Day 1 streak started. Keep it going."),

    # 21-22: Call mom reminder
    ("DONNA", "📝 Call mom"),
    ("USER", "not now, later"),

    # 23-24: Snooze acknowledged
    ("DONNA", "Alright, I'll check back in 5 hours. But don't forget - mom's waiting."),

    # 25-26: Gym reminder
    ("DONNA", "🏋️ Gym time. 30 minutes, let's go."),
    ("USER", "done! did 45 minutes today"),

    # 27-28: Gym completed
    ("DONNA", "45 minutes? Overachiever. 🔥 Day 1 streak!\n\nKeep this up and I might actually be impressed."),

    # 29-30: Follow up on call
    ("DONNA", "Hey, did you call mom yet? Still on your list."),
    ("USER", "yes just finished"),

    # 31-32: Call completed
    ("DONNA", "Done. ✅ Call mom - checked off.\n\nOne less thing on your mind."),

    # === DAY 3: Building momentum ===

    # 33-34: Morning brief (system triggered)
    ("DONNA", "☀️ *Good morning, Priyesh!* Here's your day:\n\n📅 *Today's Schedule:*\n• 3:00 PM - Dentist appointment\n\n🔄 *Habits:*\n• Drink water (🔥 2)\n• Gym workout (🔥 2)\n\nLet's make it a great day! 💪"),
    ("USER", "thanks!"),

    # 35-36: User asks about memory
    ("USER", "when is Akash's birthday again?"),
    ("DONNA", "March 15. Already in my vault. Want me to remind you a few days before?"),

    # 37-38: Confirm reminder
    ("USER", "yes please remind me 2 days before"),
    ("DONNA", "Done. I'll ping you on March 13 so you have time to get a gift. Thoughtful of you."),

    # 35-36: Evening check-in
    ("DONNA", "🌙 *End of day check-in*\n\n✅ Dentist appointment - done?\n🔥 2 habit streaks going (4 total days)\n\nHow'd the dentist go?"),
    ("USER", "yes all done, no cavities!"),

    # 37-38: Donna celebrates
    ("DONNA", "No cavities? That's what I like to hear. All tasks done for the day. Rest up - I'll see you tomorrow morning."),

    # === DAY 4: Streak building ===

    # 39-40: Morning water
    ("DONNA", "💧 Morning water check. Glass #1?"),
    ("USER", "yep, on it"),

    # 41 (bonus): Donna acknowledges
    ("DONNA", "🔥 Day 3 streak! You're getting good at this. 7 more glasses to go today."),
]


def print_conversation():
    """Print the simulated conversation."""
    print("=" * 70)
    print("DONNA AI - SIMULATED CONVERSATION")
    print("=" * 70)
    print(f"Phone: {PHONE}")
    print(f"Messages: {len(CONVERSATION)}")
    print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    for i, (sender, message) in enumerate(CONVERSATION, 1):
        print()
        if sender == "USER":
            print(f"[{i}] 👤 USER:")
            # Indent user messages
            for line in message.split("\n"):
                print(f"    {line}")
        else:
            print(f"[{i}] 🤖 DONNA:")
            # Indent Donna messages
            for line in message.split("\n"):
                print(f"    {line}")

    print()
    print("=" * 70)
    print("CONVERSATION SUMMARY")
    print("=" * 70)

    user_msgs = [m for s, m in CONVERSATION if s == "USER"]
    donna_msgs = [m for s, m in CONVERSATION if s == "DONNA"]

    print(f"User messages: {len(user_msgs)}")
    print(f"Donna messages: {len(donna_msgs)}")
    print()

    # Analyze what tools would be called
    print("TOOL CALLS DETECTED:")
    print("-" * 40)

    tools_used = {
        "update_user": 0,
        "create_task": 0,
        "create_recurring_task": 0,
        "store_memory": 0,
        "search_tasks": 0,
        "complete_task": 0,
        "snooze_task": 0,
        "search_memory": 0,
        "send_whatsapp": 0,
    }

    for msg in user_msgs:
        msg_lower = msg.lower()

        if "my name is" in msg_lower or "i'm " in msg_lower.split()[0:2]:
            tools_used["update_user"] += 1
        elif any(p in msg_lower for p in ["remind me", "reminder"]):
            if any(w in msg_lower for w in ["water", "gym", "habit"]):
                tools_used["create_recurring_task"] += 1
            else:
                tools_used["create_task"] += 1
        elif any(p in msg_lower for p in ["i want to", "help me"]) and any(w in msg_lower for w in ["water", "gym", "build"]):
            tools_used["create_recurring_task"] += 1
        elif any(p in msg_lower for p in ["remember that"]):
            tools_used["store_memory"] += 1
        elif any(p in msg_lower for p in ["what's on", "what do i have"]):
            tools_used["search_tasks"] += 1
        elif any(p in msg_lower for p in ["done", "finished", "yes just", "all done"]):
            tools_used["complete_task"] += 1
        elif any(p in msg_lower for p in ["not now", "later"]):
            tools_used["snooze_task"] += 1
        elif any(p in msg_lower for p in ["when is", "birthday again"]):
            tools_used["search_memory"] += 1
        else:
            tools_used["send_whatsapp"] += 1

    for tool, count in sorted(tools_used.items(), key=lambda x: -x[1]):
        if count > 0:
            print(f"  {tool}: {count}")

    print()
    print("FEATURES DEMONSTRATED:")
    print("-" * 40)
    features = [
        "✅ User onboarding (name capture)",
        "✅ One-time task creation with smart defaults",
        "✅ Specific time task creation",
        "✅ Habit creation (water - 4x daily)",
        "✅ Habit creation (gym - 1x morning)",
        "✅ Memory storage (birthday)",
        "✅ Task listing",
        "✅ Water reminder & completion",
        "✅ Task snoozing",
        "✅ Gym completion with streak",
        "✅ Task completion",
        "✅ Morning brief",
        "✅ Memory recall",
        "✅ Future reminder creation",
        "✅ Evening check-in",
    ]
    for feature in features:
        print(f"  {feature}")

    print()
    print("=" * 70)


if __name__ == "__main__":
    print_conversation()
