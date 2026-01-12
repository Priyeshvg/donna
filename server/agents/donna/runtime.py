"""Donna Runtime - Main execution loop for handling messages."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from ...config import get_settings
from ...logging_config import logger
from ...services.llm import get_llm_client
from ...services.database import get_database_client, User, Chat
from ...services.memory import get_memory_client
from .agent import DonnaAgent, SYSTEM_PROMPT, get_tools_schema


class DonnaRuntime:
    """Runtime for executing Donna agent conversations."""

    MAX_TOOL_ITERATIONS = 10

    def __init__(self, phone: str):
        self.phone = phone
        self.db = get_database_client()
        self.llm = get_llm_client()
        self.memory = get_memory_client()
        self.settings = get_settings()
        self.user: Optional[User] = None
        self.agent: Optional[DonnaAgent] = None

    async def execute(self, message: str, profile_name: Optional[str] = None) -> Dict[str, Any]:
        """Process an incoming message and generate response.

        Args:
            message: The user's message
            profile_name: User's WhatsApp profile name (for new users)

        Returns:
            Dict with execution results
        """
        logger.info(f"Processing message from {self.phone}: {message[:50]}...")

        # Load or create user
        self.user = await self._ensure_user(profile_name)

        # Create agent
        self.agent = DonnaAgent(self.phone, self.user)

        # Save incoming message to chat history
        await self.db.save_chat(Chat(
            phone_no=self.phone,
            chat=message,
            type="received"
        ))

        # AUTO-SEARCH MEMORY - This is the key fix!
        # Search memory for relevant context BEFORE calling the LLM
        relevant_memories = await self._search_relevant_memories(message)

        # Build context with memories included
        context = await self._build_context(message, relevant_memories)

        # Get recent chat history
        chat_history = await self._get_chat_history()

        # Build messages for LLM
        messages = self._build_messages(context, chat_history, message)

        # Run the agent loop
        responses = []
        for iteration in range(self.MAX_TOOL_ITERATIONS):
            logger.debug(f"Agent iteration {iteration + 1}")

            # Call LLM
            response = await self.llm.chat_completion(
                messages=messages,
                system=SYSTEM_PROMPT,
                tools=get_tools_schema(),
            )

            # Check for tool calls
            choice = response.get("choices", [{}])[0]
            assistant_message = choice.get("message", {})

            # Add assistant response to messages
            messages.append(assistant_message)

            # Check finish reason
            finish_reason = choice.get("finish_reason")

            if finish_reason == "tool_calls":
                # Execute tool calls
                tool_calls = assistant_message.get("tool_calls", [])
                tool_results = []

                for tool_call in tool_calls:
                    tool_name = tool_call["function"]["name"]
                    tool_args = json.loads(tool_call["function"]["arguments"])

                    result = await self.agent.execute_tool(tool_name, tool_args)
                    tool_results.append({
                        "tool_call_id": tool_call["id"],
                        "name": tool_name,
                        "result": result
                    })

                    # Track WhatsApp messages to send via n8n
                    if tool_name == "send_whatsapp" and result.get("success"):
                        responses.append({
                            "type": "text",
                            "message": result.get("message")
                        })
                    elif tool_name == "send_image" and result.get("success"):
                        responses.append({
                            "type": "image",
                            "image_url": result.get("image_url"),
                            "caption": result.get("caption")
                        })

                # Add tool results to messages
                for tr in tool_results:
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tr["tool_call_id"],
                        "content": json.dumps(tr["result"])
                    })

            elif finish_reason == "stop":
                # Agent finished - check if it returned text without calling send_whatsapp
                text_content = assistant_message.get("content", "")
                if text_content and not responses:
                    # Model responded with text directly - treat as WhatsApp message
                    logger.info("Model returned text directly, treating as WhatsApp message")
                    responses.append({
                        "type": "text",
                        "message": text_content
                    })
                    # Also save to chat history
                    await self.db.save_chat(Chat(
                        phone_no=self.phone,
                        chat=text_content,
                        type="sent"
                    ))
                logger.info(f"Agent finished after {iteration + 1} iterations")
                break

            else:
                # Unknown finish reason
                logger.warning(f"Unknown finish reason: {finish_reason}")
                break

        return {
            "success": True,
            "phone": self.phone,
            "responses": responses,
            "iterations": iteration + 1
        }

    async def _ensure_user(self, profile_name: Optional[str] = None) -> User:
        """Load existing user or create new one."""
        user = await self.db.get_user(self.phone)

        if not user:
            # Create new user - onboarding tracks usage counts
            user = User(
                phone_no=self.phone,
                name=profile_name,
                onboarding={
                    "reminder_count": 0,
                    "memory_count": 0,
                    "message_count": 0,
                }
            )
            user = await self.db.create_user(user)
            logger.info(f"Created new user: {self.phone}")

        return user

    def _should_search_memory(self, message: str) -> bool:
        """Determine if we should search memory for this message.

        Skip memory search for:
        - Simple greetings
        - Messages that are STORING new information (not retrieving)
        """
        msg_lower = message.lower().strip()

        # Simple greetings that don't need memory
        simple_patterns = {
            "hi", "hello", "hey", "yo", "sup", "hola", "namaste",
            "good morning", "good afternoon", "good evening", "good night",
            "gm", "gn", "thanks", "thank you", "ok", "okay", "bye", "goodbye",
            "yes", "no", "yep", "nope", "sure", "cool", "nice", "great",
        }

        # Skip for very short messages (likely greetings)
        if len(msg_lower) < 4:
            return False

        # Skip for known greetings
        if msg_lower in simple_patterns:
            return False

        # IMPORTANT: Skip memory search when user is STORING new info
        # Patterns that indicate storage intent (not retrieval)
        store_patterns = [
            "'s number is", "'s phone is", "'s birthday is",
            " number is ", " phone is ", " birthday is ",
            "remember that", "remember this", "save this",
            "my name is", "call me ", "i am ",
            " is my ", " are my ",  # "Sarah is my wife"
        ]
        for pattern in store_patterns:
            if pattern in msg_lower:
                logger.info(f"Skipping memory search - storage intent detected: {message[:30]}...")
                return False

        # Skip if message starts with common greeting
        for pattern in simple_patterns:
            if msg_lower.startswith(pattern + " ") or msg_lower.startswith(pattern + "!"):
                # But search if it has a question (e.g., "hi, what's pranjal's number?")
                if "?" in message or any(word in msg_lower for word in ["what", "who", "when", "where", "how", "do you know", "have you"]):
                    return True
                return False

        return True

    async def _search_relevant_memories(self, message: str) -> List[Dict[str, Any]]:
        """Auto-search memory for anything relevant to the user's message.

        This is called BEFORE the LLM to inject relevant context.
        """
        if not self.memory:
            return []

        # Skip memory search for simple messages to reduce latency
        if not self._should_search_memory(message):
            logger.info(f"Skipping memory search for simple message: {message[:30]}...")
            return []

        try:
            # Search memory with the user's message
            results = await self.memory.search(self.phone, message, top_k=10)

            # Filter for positive relevance scores (cosine similarity > 0)
            # Note: text-embedding-3-small with 1024 dims produces low scores,
            # so we accept anything with positive similarity
            relevant = [r for r in results if r.get("score", 0) > 0.01]

            if relevant:
                logger.info(f"Found {len(relevant)} relevant memories for: {message[:30]}...")

            return relevant
        except Exception as e:
            logger.error(f"Memory search failed: {e}")
            return []

    async def _build_context(self, message: str, memories: Optional[List[Dict[str, Any]]] = None) -> str:
        """Build context string for the LLM."""
        now = datetime.now()
        ist_time = now.strftime("%A, %B %d, %Y at %I:%M %p")
        iso_date = now.strftime("%Y-%m-%d")
        tomorrow = (now.replace(hour=0, minute=0, second=0) +
                   __import__('datetime').timedelta(days=1)).strftime("%Y-%m-%d")

        # Use stored name from DB, not WhatsApp profile name
        user_name = self.user.name if self.user.name else None

        # Build memories section
        memories_section = ""
        if memories:
            memories_text = []
            for mem in memories:
                # Handle both 'content' and 'text' fields (legacy support)
                content = mem.get("content") or mem.get("metadata", {}).get("text", "")
                score = mem.get("score", 0)
                if content:
                    memories_text.append(f"  • {content} (relevance: {score:.2f})")

            if memories_text:
                memories_section = f"""
═══════════════════════════════════════════════════════════
RELEVANT MEMORIES (auto-retrieved)
═══════════════════════════════════════════════════════════
{chr(10).join(memories_text)}

IMPORTANT: Use this information to respond! If user asks about something
mentioned here, USE this data - don't say you don't know.
"""

        # User info section
        user_section = f"Phone: {self.phone}"
        if user_name:
            user_section = f"User: {user_name}\n{user_section}"
        else:
            user_section = f"User: (name not set yet)\n{user_section}"

        context = f"""═══════════════════════════════════════════════════════════
CURRENT CONTEXT
═══════════════════════════════════════════════════════════
{user_section}
Time: {ist_time}
Default reminder method: {self.user.default_reminder_method}

Today: {iso_date}
Tomorrow: {tomorrow}
Time format: YYYY-MM-DDTHH:mm:ss+05:30

User's message: "{message}"
{memories_section}
═══════════════════════════════════════════════════════════
SPECIAL COMMANDS
═══════════════════════════════════════════════════════════
- "!reset": Ask for confirmation first, then execute reset_user tool after user confirms
"""
        return context

    async def _get_chat_history(self, limit: int = 20) -> List[Dict[str, str]]:
        """Get recent chat history formatted for LLM."""
        chats = await self.db.get_chats(self.phone, limit)

        history = []
        for chat in chats:
            role = "user" if chat.type == "received" else "assistant"
            history.append({
                "role": role,
                "content": chat.chat
            })

        return history

    def _build_messages(
        self,
        context: str,
        chat_history: List[Dict[str, str]],
        current_message: str
    ) -> List[Dict[str, str]]:
        """Build the messages array for the LLM."""
        messages = []

        # Add context as first user message
        messages.append({
            "role": "user",
            "content": f"<context>\n{context}\n</context>"
        })

        # Add chat history (limit to avoid token overflow)
        if chat_history:
            # Only include last 10 messages to save tokens
            recent_history = chat_history[-10:]
            for msg in recent_history:
                messages.append(msg)

        # The current message is already in context, but we signal it's the latest
        messages.append({
            "role": "user",
            "content": f"<current_message>\n{current_message}\n</current_message>\n\nRespond to this message. Use tools as needed. Always send at least one WhatsApp message."
        })

        return messages


__all__ = ["DonnaRuntime"]
