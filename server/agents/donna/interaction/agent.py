"""Donna Interaction Agent - prompt construction."""

from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone, timedelta


# IST timezone (UTC+5:30)
IST = timezone(timedelta(hours=5, minutes=30))

_prompt_path = Path(__file__).parent / "system_prompt.md"
SYSTEM_PROMPT = _prompt_path.read_text(encoding="utf-8").strip()

# Simple system prompt for quick responses (Haiku)
SIMPLE_SYSTEM_PROMPT = """You are Donna, a friendly executive assistant on WhatsApp. Be brief, warm, and direct. 1-2 sentences max. No corporate phrases like "How can I help you?" - just respond naturally like texting a friend. Never do roleplay actions like *adjusts glasses* or similar."""


def build_system_prompt(simple: bool = False) -> str:
    """Return the system prompt for the interaction agent.

    Args:
        simple: If True, return a minimal prompt for simple greetings (Haiku)
    """
    if simple:
        return SIMPLE_SYSTEM_PROMPT
    return SYSTEM_PROMPT


def prepare_message(
    user_message: str,
    user_name: Optional[str],
    phone: str,
    chat_history: List[Dict[str, str]],
    memories: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, str]]:
    """Build the message for the LLM with all context."""
    now = datetime.now(IST)
    ist_time = now.strftime("%A, %B %d, %Y at %I:%M %p IST")
    iso_date = now.strftime("%Y-%m-%d")

    # Build context section
    user_section = f"User: {user_name or '(not set)'}\nPhone: {phone}"

    # Build memories section
    memories_section = ""
    if memories:
        memories_text = []
        for mem in memories:
            content = mem.get("content") or mem.get("metadata", {}).get("text", "")
            score = mem.get("score", 0)
            if content:
                memories_text.append(f"  • {content} (relevance: {score:.2f})")

        if memories_text:
            memories_section = f"""
<relevant_memories>
{chr(10).join(memories_text)}
</relevant_memories>
"""

    # Build chat history section
    history_section = ""
    if chat_history:
        history_lines = []
        for msg in chat_history[-10:]:  # Last 10 messages
            role = "User" if msg["role"] == "user" else "Donna"
            history_lines.append(f"{role}: {msg['content']}")
        history_section = f"""
<chat_history>
{chr(10).join(history_lines)}
</chat_history>
"""

    context = f"""<context>
{user_section}
Time: {ist_time}
Today: {iso_date}
</context>
{history_section}
{memories_section}
<current_message>
{user_message}
</current_message>"""

    return [{"role": "user", "content": context}]
