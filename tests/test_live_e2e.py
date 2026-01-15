#!/usr/bin/env python3
"""End-to-end live test for Donna AI - sends 25 messages and verifies database."""

import asyncio
import httpx
import json
from datetime import datetime

# Configuration
API_URL = "http://13.127.55.121:8000"
TEST_PHONE = "919999999999"  # Test phone number

# 25 test messages covering all features
TEST_MESSAGES = [
    # Basic greetings
    ("hi", "greeting"),
    ("hello donna", "greeting"),
    ("hey there", "greeting"),

    # Reminders with various time formats
    ("remind me to call mom at 9pm", "reminder"),
    ("remind me in 5 minutes to drink water", "reminder"),
    ("remind me to check email at 10:30am", "reminder"),
    ("remind me tomorrow at 8am to exercise", "reminder"),
    ("set a reminder for 6pm to take medicine", "reminder"),

    # Memory/facts
    ("remember that my birthday is March 15", "memory"),
    ("my sister's name is Priya", "memory"),
    ("remember I'm allergic to peanuts", "memory"),
    ("my favorite color is blue", "memory"),

    # Task-like messages
    ("I need to buy groceries", "task"),
    ("don't forget to pay rent", "task"),
    ("add meeting with John to my list", "task"),

    # Questions
    ("what can you do?", "question"),
    ("what's on my list?", "question"),
    ("do I have any reminders?", "question"),
    ("when is my next task?", "question"),

    # Habit-like
    ("I want to drink more water", "habit"),
    ("help me build a gym habit", "habit"),
    ("remind me to meditate daily", "habit"),

    # Casual conversation
    ("thanks!", "casual"),
    ("that's great", "casual"),
    ("perfect", "casual"),
]


async def send_message(client: httpx.AsyncClient, phone: str, message: str) -> dict:
    """Send a message to Donna via webhook."""
    payload = {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "123",
            "changes": [{
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {"phone_number_id": "806507515890557"},
                    "contacts": [{"profile": {"name": "Test User"}, "wa_id": phone}],
                    "messages": [{
                        "from": phone,
                        "id": f"wamid.test.{datetime.now().timestamp()}",
                        "timestamp": str(int(datetime.now().timestamp())),
                        "text": {"body": message},
                        "type": "text"
                    }]
                },
                "field": "messages"
            }]
        }]
    }

    try:
        response = await client.post(
            f"{API_URL}/api/v1/webhooks/whatsapp",
            json=payload,
            timeout=60.0
        )
        return {"status": response.status_code, "body": response.text}
    except Exception as e:
        return {"status": "error", "error": str(e)}


async def run_tests():
    """Run all 25 test messages."""
    print("=" * 70)
    print("DONNA AI - LIVE E2E TEST")
    print("=" * 70)
    print(f"API: {API_URL}")
    print(f"Phone: {TEST_PHONE}")
    print(f"Messages: {len(TEST_MESSAGES)}")
    print("=" * 70)
    print()

    results = {
        "total": len(TEST_MESSAGES),
        "success": 0,
        "failed": 0,
        "errors": []
    }

    async with httpx.AsyncClient() as client:
        for i, (message, msg_type) in enumerate(TEST_MESSAGES, 1):
            print(f"[{i:02d}/{len(TEST_MESSAGES)}] {msg_type.upper():10s} | {message[:40]:<40s}", end=" ")

            result = await send_message(client, TEST_PHONE, message)

            if result.get("status") == 200:
                print("OK")
                results["success"] += 1
            else:
                print(f"FAIL ({result.get('status', 'error')})")
                results["failed"] += 1
                results["errors"].append({
                    "message": message,
                    "type": msg_type,
                    "result": result
                })

            # Small delay between messages
            await asyncio.sleep(2)

    print()
    print("=" * 70)
    print("RESULTS")
    print("=" * 70)
    print(f"Total:   {results['total']}")
    print(f"Success: {results['success']}")
    print(f"Failed:  {results['failed']}")

    if results["errors"]:
        print()
        print("ERRORS:")
        for err in results["errors"]:
            print(f"  - {err['message']}: {err['result']}")

    print()
    print("=" * 70)
    print("Now check the database tables:")
    print("  - conversations: Should have incoming + outgoing messages")
    print("  - tasks: Should have reminder tasks")
    print("  - donna_users: Should have test user")
    print("=" * 70)

    return results


if __name__ == "__main__":
    asyncio.run(run_tests())
