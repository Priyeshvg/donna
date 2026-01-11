"""Database client supporting Nhost GraphQL and local SQLite fallback."""

from __future__ import annotations

import os
import json
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Dict, List, Optional
from functools import lru_cache

import httpx

from ...logging_config import logger
from .models import User, Schedule, Chat, Trigger


class DatabaseClient(ABC):
    """Abstract database client interface."""

    # User operations
    @abstractmethod
    async def get_user(self, phone: str) -> Optional[User]:
        """Get user by phone number."""
        pass

    @abstractmethod
    async def create_user(self, user: User) -> User:
        """Create a new user."""
        pass

    @abstractmethod
    async def update_user(self, phone: str, updates: Dict[str, Any]) -> Optional[User]:
        """Update user fields."""
        pass

    @abstractmethod
    async def delete_user(self, phone: str) -> bool:
        """Delete user by phone."""
        pass

    # Schedule operations
    @abstractmethod
    async def get_schedules(self, phone: str, status: Optional[str] = None) -> List[Schedule]:
        """Get schedules for a phone number."""
        pass

    @abstractmethod
    async def create_schedule(self, schedule: Schedule) -> Schedule:
        """Create a new schedule/reminder."""
        pass

    @abstractmethod
    async def update_schedule(self, schedule_id: str, updates: Dict[str, Any]) -> Optional[Schedule]:
        """Update schedule fields."""
        pass

    @abstractmethod
    async def delete_schedules(self, phone: str) -> int:
        """Delete all schedules for a phone. Returns count deleted."""
        pass

    @abstractmethod
    async def get_due_schedules(self, before: datetime) -> List[Schedule]:
        """Get schedules due before given time."""
        pass

    # Chat operations
    @abstractmethod
    async def save_chat(self, chat: Chat) -> Chat:
        """Save a chat message."""
        pass

    @abstractmethod
    async def get_chats(self, phone: str, limit: int = 20) -> List[Chat]:
        """Get recent chats for a phone number."""
        pass

    @abstractmethod
    async def delete_chats(self, phone: str) -> int:
        """Delete all chats for a phone. Returns count deleted."""
        pass


class NhostClient(DatabaseClient):
    """Nhost GraphQL client for production."""

    def __init__(self, endpoint: str, admin_secret: str):
        self.endpoint = endpoint
        self.headers = {
            "Content-Type": "application/json",
            "x-hasura-admin-secret": admin_secret,
        }
        self._client = httpx.AsyncClient(timeout=30.0)

    async def _execute(self, query: str, variables: Dict[str, Any] = None) -> Dict[str, Any]:
        """Execute a GraphQL query."""
        payload = {"query": query}
        if variables:
            payload["variables"] = variables

        try:
            response = await self._client.post(
                self.endpoint,
                json=payload,
                headers=self.headers,
            )
            response.raise_for_status()
            result = response.json()

            if "errors" in result:
                logger.error(f"GraphQL errors: {result['errors']}")
                raise Exception(f"GraphQL error: {result['errors']}")

            return result.get("data", {})
        except Exception as e:
            logger.error(f"Nhost query failed: {e}")
            raise

    # User operations
    async def get_user(self, phone: str) -> Optional[User]:
        query = """
        query GetUser($phone: String!) {
            user_phone_no(where: {phone_no: {_eq: $phone}}) {
                id phone_no name email user_context default_reminder_method
                timezone daily_checkin_enabled daily_checkin_time pin_status
                onboarding created_at updated_at
            }
        }
        """
        data = await self._execute(query, {"phone": phone})
        users = data.get("user_phone_no", [])
        if users:
            return User(**users[0])
        return None

    async def create_user(self, user: User) -> User:
        query = """
        mutation CreateUser($object: user_phone_no_insert_input!) {
            insert_user_phone_no_one(object: $object) {
                id phone_no name email user_context default_reminder_method
                timezone daily_checkin_enabled daily_checkin_time pin_status
                onboarding created_at updated_at
            }
        }
        """
        obj = {
            "phone_no": user.phone_no,
            "name": user.name,
            "email": user.email,
            "user_context": user.user_context,
            "default_reminder_method": user.default_reminder_method,
            "timezone": user.timezone,
            "onboarding": user.onboarding,
        }
        data = await self._execute(query, {"object": obj})
        return User(**data["insert_user_phone_no_one"])

    async def update_user(self, phone: str, updates: Dict[str, Any]) -> Optional[User]:
        # Build dynamic set clause
        set_fields = ", ".join(f"{k}: ${k}" for k in updates.keys())
        var_defs = ", ".join(f"${k}: {self._gql_type(v)}" for k, v in updates.items())

        query = f"""
        mutation UpdateUser($phone: String!, {var_defs}) {{
            update_user_phone_no(
                where: {{phone_no: {{_eq: $phone}}}},
                _set: {{{set_fields}}}
            ) {{
                returning {{
                    id phone_no name email user_context default_reminder_method
                    timezone daily_checkin_enabled daily_checkin_time pin_status
                    onboarding created_at updated_at
                }}
            }}
        }}
        """
        variables = {"phone": phone, **updates}
        data = await self._execute(query, variables)
        returning = data.get("update_user_phone_no", {}).get("returning", [])
        if returning:
            return User(**returning[0])
        return None

    async def delete_user(self, phone: str) -> bool:
        query = """
        mutation DeleteUser($phone: String!) {
            delete_user_phone_no(where: {phone_no: {_eq: $phone}}) {
                affected_rows
            }
        }
        """
        data = await self._execute(query, {"phone": phone})
        return data.get("delete_user_phone_no", {}).get("affected_rows", 0) > 0

    # Schedule operations
    async def get_schedules(self, phone: str, status: Optional[str] = None) -> List[Schedule]:
        where_clause = '{phone_number: {_eq: $phone}}'
        if status:
            where_clause = '{phone_number: {_eq: $phone}, call_status: {_eq: $status}}'

        query = f"""
        query GetSchedules($phone: String!, $status: String) {{
            schedule(
                where: {where_clause},
                order_by: {{call_time: asc}},
                limit: 50
            ) {{
                id user_id phone_number call_time context call_status task_status
                habit_type importance reminder_method rich_context follow_up_time
                follow_up_count reminder_sent is_recurring recurrence_rule
                created_at updated_at
            }}
        }}
        """
        variables = {"phone": phone}
        if status:
            variables["status"] = status
        data = await self._execute(query, variables)
        return [Schedule(**s) for s in data.get("schedule", [])]

    async def create_schedule(self, schedule: Schedule) -> Schedule:
        query = """
        mutation CreateSchedule($object: schedule_insert_input!) {
            insert_schedule_one(object: $object) {
                id user_id phone_number call_time context call_status task_status
                habit_type importance reminder_method rich_context follow_up_time
                follow_up_count reminder_sent is_recurring recurrence_rule
                created_at updated_at
            }
        }
        """
        obj = {
            "user_id": schedule.user_id,
            "phone_number": schedule.phone_number,
            "call_time": schedule.call_time.isoformat() if schedule.call_time else None,
            "context": schedule.context,
            "call_status": schedule.call_status,
            "task_status": schedule.task_status,
            "habit_type": schedule.habit_type,
            "importance": schedule.importance,
            "reminder_method": schedule.reminder_method,
            "rich_context": schedule.rich_context,
            "follow_up_time": schedule.follow_up_time.isoformat() if schedule.follow_up_time else None,
            "follow_up_count": schedule.follow_up_count,
            "reminder_sent": schedule.reminder_sent,
            "is_recurring": schedule.is_recurring,
            "recurrence_rule": schedule.recurrence_rule,
        }
        # Remove None values
        obj = {k: v for k, v in obj.items() if v is not None}
        data = await self._execute(query, {"object": obj})
        return Schedule(**data["insert_schedule_one"])

    async def update_schedule(self, schedule_id: str, updates: Dict[str, Any]) -> Optional[Schedule]:
        query = """
        mutation UpdateSchedule($id: uuid!, $set: schedule_set_input!) {
            update_schedule_by_pk(pk_columns: {id: $id}, _set: $set) {
                id user_id phone_number call_time context call_status task_status
                habit_type importance reminder_method rich_context follow_up_time
                follow_up_count reminder_sent is_recurring recurrence_rule
                created_at updated_at
            }
        }
        """
        data = await self._execute(query, {"id": schedule_id, "set": updates})
        result = data.get("update_schedule_by_pk")
        if result:
            return Schedule(**result)
        return None

    async def delete_schedules(self, phone: str) -> int:
        query = """
        mutation DeleteSchedules($phone: String!) {
            delete_schedule(where: {phone_number: {_eq: $phone}}) {
                affected_rows
            }
        }
        """
        data = await self._execute(query, {"phone": phone})
        return data.get("delete_schedule", {}).get("affected_rows", 0)

    async def get_due_schedules(self, before: datetime) -> List[Schedule]:
        query = """
        query GetDueSchedules($before: timestamptz!) {
            schedule(
                where: {
                    call_time: {_lte: $before},
                    call_status: {_eq: "pending"},
                    reminder_sent: {_eq: false}
                },
                order_by: {call_time: asc}
            ) {
                id user_id phone_number call_time context call_status task_status
                habit_type importance reminder_method rich_context follow_up_time
                follow_up_count reminder_sent is_recurring recurrence_rule
                created_at updated_at
            }
        }
        """
        data = await self._execute(query, {"before": before.isoformat()})
        return [Schedule(**s) for s in data.get("schedule", [])]

    # Chat operations
    async def save_chat(self, chat: Chat) -> Chat:
        query = """
        mutation SaveChat($object: chats_insert_input!) {
            insert_chats_one(object: $object) {
                id phone_no chat type created_at updated_at
            }
        }
        """
        obj = {
            "phone_no": chat.phone_no,
            "chat": chat.chat,
            "type": chat.type,
        }
        data = await self._execute(query, {"object": obj})
        return Chat(**data["insert_chats_one"])

    async def get_chats(self, phone: str, limit: int = 20) -> List[Chat]:
        query = """
        query GetChats($phone: String!, $limit: Int!) {
            chats(
                where: {phone_no: {_eq: $phone}},
                order_by: {created_at: desc},
                limit: $limit
            ) {
                id phone_no chat type created_at updated_at
            }
        }
        """
        data = await self._execute(query, {"phone": phone, "limit": limit})
        # Reverse to get chronological order
        chats = data.get("chats", [])
        return [Chat(**c) for c in reversed(chats)]

    async def delete_chats(self, phone: str) -> int:
        query = """
        mutation DeleteChats($phone: String!) {
            delete_chats(where: {phone_no: {_eq: $phone}}) {
                affected_rows
            }
        }
        """
        data = await self._execute(query, {"phone": phone})
        return data.get("delete_chats", {}).get("affected_rows", 0)

    def _gql_type(self, value: Any) -> str:
        """Infer GraphQL type from Python value."""
        if isinstance(value, bool):
            return "Boolean"
        elif isinstance(value, int):
            return "Int"
        elif isinstance(value, float):
            return "Float"
        elif isinstance(value, dict):
            return "jsonb"
        else:
            return "String"


# Singleton instance
_db_client: Optional[DatabaseClient] = None


def get_database_client() -> DatabaseClient:
    """Get the singleton database client."""
    global _db_client
    if _db_client is None:
        # Check for Nhost configuration
        nhost_endpoint = os.getenv("NHOST_GRAPHQL_ENDPOINT")
        nhost_secret = os.getenv("NHOST_ADMIN_SECRET")

        if nhost_endpoint and nhost_secret:
            logger.info(f"Using Nhost database: {nhost_endpoint}")
            _db_client = NhostClient(nhost_endpoint, nhost_secret)
        else:
            raise ValueError(
                "Database not configured. Set NHOST_GRAPHQL_ENDPOINT and NHOST_ADMIN_SECRET"
            )

    return _db_client


__all__ = ["DatabaseClient", "get_database_client", "NhostClient"]
