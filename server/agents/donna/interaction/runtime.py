"""Donna Interaction Agent Runtime."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from ....config import get_settings
from ....logging_config import logger
from ....services.llm import get_llm_client
from ....services.llm.client import is_simple_message
from ....services.database import get_database_client, User, Chat
from ....services.memory import get_memory_client
from .agent import build_system_prompt, prepare_message
from .tools import get_tool_schemas, handle_tool_call


class InteractionRuntime:
    """Runtime for the Donna Interaction Agent."""

    MAX_TOOL_ITERATIONS = 5

    def __init__(self, phone: str, user: User):
        self.phone = phone
        self.user = user
        self.db = get_database_client()
        self.llm = get_llm_client()
        self.memory = get_memory_client()

    async def execute(
        self,
        message: str,
        chat_history: List[Dict[str, str]],
        memories: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Process a user message through the interaction agent.

        Returns:
            Dict with:
            - whatsapp_messages: List of messages to send to user
            - agent_tasks: List of tasks to dispatch to execution agents
        """
        # Build the messages for LLM
        messages = prepare_message(
            user_message=message,
            user_name=self.user.name,
            phone=self.phone,
            chat_history=chat_history,
            memories=memories,
        )

        whatsapp_messages = []
        agent_tasks = []

        # For simple greetings, skip tools entirely and use Haiku (10x faster)
        is_simple = is_simple_message(message)
        tools = None if is_simple else get_tool_schemas()

        # Select model explicitly (Haiku for simple, Sonnet for complex)
        model = "anthropic/claude-3-5-haiku" if is_simple else None
        if is_simple:
            logger.info(f"Using Haiku for simple message: {message[:30]}")

        # Run the interaction loop
        for iteration in range(self.MAX_TOOL_ITERATIONS):
            logger.debug(f"Interaction agent iteration {iteration + 1}")

            # Call LLM (use simple prompt for Haiku)
            response = await self.llm.chat_completion(
                messages=messages,
                system=build_system_prompt(simple=is_simple),
                tools=tools,
                model=model,
            )

            choice = response.get("choices", [{}])[0]
            assistant_message = choice.get("message", {})
            finish_reason = choice.get("finish_reason")

            # Add assistant message to conversation
            messages.append(assistant_message)

            if finish_reason == "tool_calls":
                # Process tool calls
                tool_calls = assistant_message.get("tool_calls", [])

                for tool_call in tool_calls:
                    tool_name = tool_call["function"]["name"]
                    tool_args = json.loads(tool_call["function"]["arguments"])

                    result = handle_tool_call(tool_name, tool_args)

                    # Collect WhatsApp messages
                    if result.whatsapp_message:
                        whatsapp_messages.append(result.whatsapp_message)

                    # Collect agent tasks
                    if result.agent_task:
                        agent_tasks.append(result.agent_task)

                    # Add tool result to messages
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call["id"],
                        "content": json.dumps(result.payload)
                    })

            elif finish_reason == "stop":
                # Check for direct text response
                text_content = assistant_message.get("content", "")
                if text_content and not whatsapp_messages:
                    whatsapp_messages.append(text_content)
                break

            else:
                logger.warning(f"Unknown finish reason: {finish_reason}")
                break

        return {
            "whatsapp_messages": whatsapp_messages,
            "agent_tasks": agent_tasks,
        }
