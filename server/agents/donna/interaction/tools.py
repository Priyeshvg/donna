"""Tool definitions for Donna Interaction Agent."""

import json
from dataclasses import dataclass
from typing import Any, Dict, Optional

from ....logging_config import logger


@dataclass
class ToolResult:
    """Result from a tool execution."""
    success: bool
    payload: Any = None
    whatsapp_message: Optional[str] = None
    agent_task: Optional[Dict[str, Any]] = None


# Tool schemas for the Interaction Agent
TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "send_whatsapp",
            "description": "Send a WhatsApp message to the user. Use for all responses.",
            "parameters": {
                "type": "object",
                "properties": {
                    "message": {
                        "type": "string",
                        "description": "The message to send to the user"
                    }
                },
                "required": ["message"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "send_to_agent",
            "description": "Dispatch a task to an execution agent. Use for reminders, memory, calendar operations.",
            "parameters": {
                "type": "object",
                "properties": {
                    "agent": {
                        "type": "string",
                        "enum": ["reminder", "memory", "calendar", "reset"],
                        "description": "Which agent to dispatch to"
                    },
                    "action": {
                        "type": "string",
                        "description": "What action to perform. For reminder: create, update, delete, list. For memory: store, search."
                    },
                    "params": {
                        "type": "object",
                        "description": "Parameters for the action. For reminder.create: {task: 'what to do', time: 'when (e.g. 9pm, tomorrow 7pm, in 5 mins)'}. For reminder.update: {id: 'task_id', time: 'new time'}. For memory.store: {content: 'what to remember'}. For memory.search: {query: 'what to search for'}.",
                        "properties": {
                            "task": {"type": "string", "description": "Description of the task/reminder"},
                            "time": {"type": "string", "description": "When to remind (e.g. '9pm', 'tomorrow 7pm', 'in 5 mins')"},
                            "id": {"type": "string", "description": "Task ID for updates"},
                            "content": {"type": "string", "description": "Content to store in memory"},
                            "query": {"type": "string", "description": "Search query for memory"}
                        }
                    }
                },
                "required": ["agent", "action"]
            }
        }
    },
]


def get_tool_schemas():
    """Return tool schemas for LLM."""
    return TOOL_SCHEMAS


def handle_tool_call(name: str, arguments: Any) -> ToolResult:
    """Handle a tool call from the interaction agent."""
    try:
        if isinstance(arguments, str):
            args = json.loads(arguments) if arguments.strip() else {}
        elif isinstance(arguments, dict):
            args = arguments
        else:
            return ToolResult(success=False, payload={"error": "Invalid arguments"})

        if name == "send_whatsapp":
            return _send_whatsapp(args.get("message", ""))
        elif name == "send_to_agent":
            return _send_to_agent(
                args.get("agent"),
                args.get("action"),
                args.get("params", {})
            )
        else:
            return ToolResult(success=False, payload={"error": f"Unknown tool: {name}"})

    except Exception as e:
        logger.error(f"Tool call failed: {name} - {e}")
        return ToolResult(success=False, payload={"error": str(e)})


def _send_whatsapp(message: str) -> ToolResult:
    """Send a WhatsApp message to the user."""
    if not message:
        return ToolResult(success=False, payload={"error": "Empty message"})

    return ToolResult(
        success=True,
        payload={"status": "sent"},
        whatsapp_message=message
    )


def _send_to_agent(agent: str, action: str, params: Dict[str, Any]) -> ToolResult:
    """Dispatch a task to an execution agent."""
    if not agent or not action:
        return ToolResult(success=False, payload={"error": "Missing agent or action"})

    valid_agents = {"reminder", "memory", "calendar", "reset"}
    if agent not in valid_agents:
        return ToolResult(success=False, payload={"error": f"Unknown agent: {agent}"})

    return ToolResult(
        success=True,
        payload={"status": "dispatched", "agent": agent, "action": action},
        agent_task={"agent": agent, "action": action, "params": params}
    )
