"""Donna Runtime v2 - OpenPoke-style architecture.

This runtime uses:
1. Interaction Agent - handles conversation, dispatches tasks
2. Execution Agents - handle specific tasks (reminders, memory, calendar)

Speed optimizations:
- Redis working memory (instant context loading)
- User caching (TTL 5 minutes)
- Parallel DB calls where possible
- NO auto memory search (LLM decides via tools)
- Haiku for simple messages
- Prompt caching for system prompts
- Background memory extraction (doesn't block response)
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List, Optional

from ...config import get_settings
from ...logging_config import logger
from ...services.database import get_database_client, User, Chat
from ...services.memory import get_memory_client, extract_memories
from ...services.whatsapp import get_whatsapp_client
from ...services.cache import get_cache_client

from .interaction import InteractionRuntime
from .execution import execute_agent_task


# Fallback in-memory cache (used when Redis unavailable)
_user_cache: Dict[str, tuple] = {}  # phone -> (user, timestamp)
USER_CACHE_TTL = 300  # 5 minutes


def _get_cached_user(phone: str) -> Optional[User]:
    """Get user from in-memory cache if not expired."""
    if phone in _user_cache:
        user, ts = _user_cache[phone]
        if time.time() - ts < USER_CACHE_TTL:
            return user
        del _user_cache[phone]
    return None


def _cache_user(phone: str, user: User) -> None:
    """Cache user data in memory."""
    _user_cache[phone] = (user, time.time())


class DonnaRuntimeV2:
    """Donna Runtime using Interaction + Execution agent pattern."""

    def __init__(self, phone: str):
        self.phone = phone
        self.db = get_database_client()
        self.memory = get_memory_client()
        self.cache = get_cache_client()
        self.user: Optional[User] = None

    async def execute(self, message: str, profile_name: Optional[str] = None) -> Dict[str, Any]:
        """Process an incoming message.

        Args:
            message: The user's message
            profile_name: WhatsApp profile name (for new users)

        Returns:
            Dict with responses to send
        """
        logger.info(f"Processing message from {self.phone}: {message[:50]}...")

        # 1. PARALLEL: Load user (cached), save message, get session from Redis
        user_task = self._ensure_user(profile_name)
        save_task = self.db.save_chat(Chat(
            phone_no=self.phone,
            chat=message,
            type="received"
        ))
        session_task = self._get_session_context()

        user_result, _, session = await asyncio.gather(user_task, save_task, session_task)
        self.user, is_new_user = user_result

        # 2. Get chat history (prefer Redis session, fallback to DB)
        if session and session.get("messages"):
            chat_history = session["messages"]
            logger.debug(f"Using Redis session ({len(chat_history)} messages)")
        else:
            chat_history = await self._get_chat_history()
            logger.debug(f"Using DB history ({len(chat_history)} messages)")

        # 3. Run Interaction Agent (handles memory search internally if needed)
        interaction = InteractionRuntime(self.phone, self.user)
        interaction_result = await interaction.execute(
            message=message,
            chat_history=chat_history,
            memories=[],  # LLM will search if needed via tools
        )

        # 4. Agent tasks already executed inline by interaction runtime
        whatsapp_messages = interaction_result.get("whatsapp_messages", [])
        # agent_tasks are already executed, just logged for debugging

        # 5. Send WhatsApp messages and save to chat history
        responses = []
        whatsapp = get_whatsapp_client()

        # Send welcome messages for new users FIRST
        if is_new_user:
            user_name = self.user.name or "there"
            welcome_msgs = [
                f"Hi {user_name} 👋, I'm Donna — your assistant who gets things done 💅",
                "I handle reminders ⏰, memory 🧠, and keeping you on track 💬\nTry me now 😉"
            ]
            for welcome_msg in welcome_msgs:
                await self.db.save_chat(Chat(
                    phone_no=self.phone,
                    chat=welcome_msg,
                    type="sent"
                ))
                if whatsapp:
                    await whatsapp.send_text(self.phone, welcome_msg)
                responses.append({"type": "text", "message": welcome_msg})

        for msg in whatsapp_messages:
            # Save to chat history
            await self.db.save_chat(Chat(
                phone_no=self.phone,
                chat=msg,
                type="sent"
            ))

            # Send via WhatsApp API
            if whatsapp:
                await whatsapp.send_text(self.phone, msg)

            responses.append({"type": "text", "message": msg})

        # 6. Background tasks (don't block response)
        # - Update Redis session
        # - Extract memories from conversation (every 5 messages)
        asyncio.create_task(self._update_session(message, whatsapp_messages))

        # Run memory extraction periodically (not on every message)
        full_history = chat_history + [
            {"role": "user", "content": message},
            *[{"role": "assistant", "content": m} for m in whatsapp_messages]
        ]
        if len(full_history) >= 5 and len(full_history) % 5 == 0:
            asyncio.create_task(self._extract_memories(full_history))

        return {
            "success": True,
            "phone": self.phone,
            "responses": responses,
        }

    async def _ensure_user(self, profile_name: Optional[str] = None) -> tuple[User, bool]:
        """Load existing user (cached) or create new one.

        Returns:
            Tuple of (user, is_new_user)
        """
        # Check cache first
        cached = _get_cached_user(self.phone)
        if cached:
            logger.debug(f"User cache hit for {self.phone}")
            return cached, False

        # Load from DB
        user = await self.db.get_user(self.phone)
        is_new = False

        if not user:
            user = User(
                phone=self.phone,
                name=profile_name,
            )
            user = await self.db.create_user(user)
            logger.info(f"Created new user: {self.phone}")
            is_new = True

        # Cache for future requests
        _cache_user(self.phone, user)
        return user, is_new

    async def _get_chat_history(self, limit: int = 20) -> List[Dict[str, str]]:
        """Get recent chat history from database."""
        chats = await self.db.get_chats(self.phone, limit)

        history = []
        for chat in chats:
            role = "user" if chat.type == "received" else "assistant"
            history.append({"role": role, "content": chat.chat})

        return history

    async def _get_session_context(self) -> Optional[Dict[str, Any]]:
        """Get session context from Redis (instant)."""
        if not self.cache:
            return None
        try:
            return await self.cache.get_session(self.phone)
        except Exception as e:
            logger.warning(f"Failed to get session from Redis: {e}")
            return None

    async def _update_session(self, user_message: str, assistant_messages: List[str]) -> None:
        """Update Redis session with new messages (background task)."""
        if not self.cache:
            return
        try:
            # Add user message
            await self.cache.update_session_messages(
                self.phone, "user", user_message
            )
            # Add assistant messages
            for msg in assistant_messages:
                await self.cache.update_session_messages(
                    self.phone, "assistant", msg
                )
            logger.debug(f"Updated Redis session for {self.phone}")
        except Exception as e:
            logger.warning(f"Failed to update Redis session: {e}")

    async def _extract_memories(self, messages: List[Dict[str, str]]) -> None:
        """Extract memories from conversation (background task)."""
        try:
            result = await extract_memories(self.phone, messages)
            if result:
                logger.info(f"Memory extraction: {result}")
        except Exception as e:
            logger.warning(f"Memory extraction failed: {e}")


__all__ = ["DonnaRuntimeV2"]
