"""Donna Runtime - Main execution loop for handling messages."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from ...config import get_settings
from ...logging_config import logger
from ...services.llm import get_llm_client
from ...services.database import get_database_client, User, Chat
from .agent import DonnaAgent, SYSTEM_PROMPT, get_tools_schema


class DonnaRuntime:
    """Runtime for executing Donna agent conversations."""

    MAX_TOOL_ITERATIONS = 10

    def __init__(self, phone: str):
        self.phone = phone
        self.db = get_database_client()
        self.llm = get_llm_client()
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

        # Build context
        context = await self._build_context(message)

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
                # Agent finished
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
            # Create new user
            user = User(
                phone_no=self.phone,
                name=profile_name,
                onboarding={
                    "step": 0,
                    "intro_shown": False,
                    "first_reminder": False,
                    "preference_asked": False
                }
            )
            user = await self.db.create_user(user)
            logger.info(f"Created new user: {self.phone}")

        return user

    async def _build_context(self, message: str) -> str:
        """Build context string for the LLM."""
        now = datetime.now()
        ist_time = now.strftime("%A, %B %d, %Y at %I:%M %p")
        iso_date = now.strftime("%Y-%m-%d")
        tomorrow = (now.replace(hour=0, minute=0, second=0) +
                   __import__('datetime').timedelta(days=1)).strftime("%Y-%m-%d")

        user_name = self.user.name or "there"
        onboarding = self.user.onboarding or {}

        onboarding_info = (
            f"step={onboarding.get('step', 0)}, "
            f"intro_shown={onboarding.get('intro_shown', False)}, "
            f"first_reminder={onboarding.get('first_reminder', False)}, "
            f"preference_asked={onboarding.get('preference_asked', False)}"
        )

        context = f"""═══════════════════════════════════════════════════════════
CURRENT CONTEXT
═══════════════════════════════════════════════════════════
User: {user_name}
Phone: {self.phone}
Time: {ist_time}
Default reminder method: {self.user.default_reminder_method}
Onboarding: {onboarding_info}

Today: {iso_date}
Tomorrow: {tomorrow}
Time format: YYYY-MM-DDTHH:mm:ss+05:30

User's message: "{message}"

═══════════════════════════════════════════════════════════
SPECIAL HANDLING
═══════════════════════════════════════════════════════════
- If message is "!reset": Ask for confirmation first
- If message is "confirm reset": Execute reset_user tool
- If new user (step 0): Run onboarding intro
- If step 1 and creating first reminder: Send pin image after

Pin image URL: https://res.cloudinary.com/dfohiowls/image/upload/v1766178540/IMG_9942_2_opa5ji.jpg
Pin caption: "Quick tip: Pin me to the top so I'm always here when you need me 📌"
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
