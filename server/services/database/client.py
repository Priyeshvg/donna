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

    MAX_RETRIES = 2
    RETRY_DELAY = 0.5  # seconds

    def __init__(self, endpoint: str, admin_secret: str):
        self.endpoint = endpoint
        self.headers = {
            "Content-Type": "application/json",
            "x-hasura-admin-secret": admin_secret,
        }
        self._client = httpx.AsyncClient(timeout=30.0)

    async def _execute(self, query: str, variables: Dict[str, Any] = None) -> Dict[str, Any]:
        """Execute a GraphQL query with retry logic."""
        import asyncio

        payload = {"query": query}
        if variables:
            payload["variables"] = variables

        last_error = None
        for attempt in range(self.MAX_RETRIES + 1):
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
            except (httpx.TimeoutException, httpx.HTTPStatusError) as e:
                last_error = e
                if attempt < self.MAX_RETRIES:
                    logger.warning(f"Nhost query failed (attempt {attempt + 1}), retrying: {e}")
                    await asyncio.sleep(self.RETRY_DELAY * (attempt + 1))
                else:
                    logger.error(f"Nhost query failed after {self.MAX_RETRIES + 1} attempts: {e}")
                    raise
            except Exception as e:
                logger.error(f"Nhost query failed: {e}")
                raise

        raise last_error

    # User operations - using donna_users table (v2)
    async def get_user(self, phone: str) -> Optional[User]:
        query = """
        query GetUser($phone: String!) {
            donna_users(where: {phone: {_eq: $phone}}) {
                id phone name timezone preferences created_at updated_at
            }
        }
        """
        data = await self._execute(query, {"phone": phone})
        users = data.get("donna_users", [])
        if users:
            u = users[0]
            # Map v2 fields to User model (use 'phone' not 'phone_no')
            return User(
                id=u.get("id"),
                phone=u.get("phone"),
                name=u.get("name"),
                timezone=u.get("timezone") or "Asia/Kolkata",
                created_at=u.get("created_at"),
                updated_at=u.get("updated_at"),
            )
        return None

    async def create_user(self, user: User) -> User:
        query = """
        mutation CreateUser($object: donna_users_insert_input!) {
            insert_donna_users_one(object: $object) {
                id phone name timezone preferences created_at updated_at
            }
        }
        """
        obj = {
            "phone": user.phone,  # Use user.phone (v2 model field)
            "name": user.name,
            "timezone": user.timezone or "Asia/Kolkata",
        }
        data = await self._execute(query, {"object": obj})
        u = data["insert_donna_users_one"]
        return User(
            id=u.get("id"),
            phone=u.get("phone"),
            name=u.get("name"),
            timezone=u.get("timezone") or "Asia/Kolkata",
            created_at=u.get("created_at"),
            updated_at=u.get("updated_at"),
        )

    async def update_user(self, phone: str, updates: Dict[str, Any]) -> Optional[User]:
        # Map old field names to new v2 field names
        field_map = {"phone_no": "phone"}
        mapped_updates = {field_map.get(k, k): v for k, v in updates.items()}

        # Build dynamic set clause
        set_fields = ", ".join(f"{k}: ${k}" for k in mapped_updates.keys())
        var_defs = ", ".join(f"${k}: {self._gql_type(v)}" for k, v in mapped_updates.items())

        query = f"""
        mutation UpdateUser($phone: String!, {var_defs}) {{
            update_donna_users(
                where: {{phone: {{_eq: $phone}}}},
                _set: {{{set_fields}}}
            ) {{
                returning {{
                    id phone name timezone preferences created_at updated_at
                }}
            }}
        }}
        """
        variables = {"phone": phone, **mapped_updates}
        data = await self._execute(query, variables)
        returning = data.get("update_donna_users", {}).get("returning", [])
        if returning:
            u = returning[0]
            return User(
                id=u.get("id"),
                phone=u.get("phone"),
                name=u.get("name"),
                timezone=u.get("timezone") or "Asia/Kolkata",
                created_at=u.get("created_at"),
                updated_at=u.get("updated_at"),
            )
        return None

    async def delete_user(self, phone: str) -> bool:
        query = """
        mutation DeleteUser($phone: String!) {
            delete_donna_users(where: {phone: {_eq: $phone}}) {
                affected_rows
            }
        }
        """
        data = await self._execute(query, {"phone": phone})
        return data.get("delete_donna_users", {}).get("affected_rows", 0) > 0

    # Schedule operations - using tasks table (v2)
    async def get_schedules(self, phone: str, status: Optional[str] = None) -> List[Schedule]:
        # Map old status values to new
        status_map = {"pending": "pending", "completed": "completed", "cancelled": "dropped"}
        mapped_status = status_map.get(status, status) if status else None

        where_clause = '{user_phone: {_eq: $phone}}'
        if mapped_status:
            where_clause = '{user_phone: {_eq: $phone}, status: {_eq: $status}}'

        query = f"""
        query GetSchedules($phone: String!, $status: String) {{
            tasks(
                where: {where_clause},
                order_by: {{remind_at: asc}},
                limit: 50
            ) {{
                id user_phone title description status priority
                remind_at due_date completed_at accountability metadata
                created_at updated_at
            }}
        }}
        """
        variables = {"phone": phone}
        if mapped_status:
            variables["status"] = mapped_status
        data = await self._execute(query, variables)

        # Map v2 tasks to Schedule model
        schedules = []
        for t in data.get("tasks", []):
            acc = t.get("accountability") or {}
            schedules.append(Schedule(
                id=t.get("id"),
                phone_number=t.get("user_phone"),
                call_time=t.get("remind_at"),
                context=t.get("title"),
                call_status=t.get("status"),
                reminder_sent=t.get("status") == "reminded",
                follow_up_count=acc.get("reminder_count", 0),
                created_at=t.get("created_at"),
                updated_at=t.get("updated_at"),
            ))
        return schedules

    async def create_schedule(self, schedule: Schedule) -> Schedule:
        query = """
        mutation CreateSchedule($object: tasks_insert_input!) {
            insert_tasks_one(object: $object) {
                id user_phone title description status priority
                remind_at due_date completed_at accountability metadata
                created_at updated_at
            }
        }
        """
        obj = {
            "user_phone": schedule.phone_number,
            "title": schedule.context or "Reminder",
            "status": "pending",
            "remind_at": schedule.call_time.isoformat() if schedule.call_time else None,
        }
        # Remove None values
        obj = {k: v for k, v in obj.items() if v is not None}
        data = await self._execute(query, {"object": obj})
        t = data["insert_tasks_one"]
        return Schedule(
            id=t.get("id"),
            phone_number=t.get("user_phone"),
            call_time=t.get("remind_at"),
            context=t.get("title"),
            call_status=t.get("status"),
            created_at=t.get("created_at"),
            updated_at=t.get("updated_at"),
        )

    async def update_schedule(self, schedule_id: str, updates: Dict[str, Any]) -> Optional[Schedule]:
        # Map old field names to new
        field_map = {
            "call_status": "status",
            "reminder_sent": None,  # Handled differently in v2
            "call_time": "remind_at",
            "context": "title",
        }
        mapped_updates = {}
        for k, v in updates.items():
            new_key = field_map.get(k, k)
            if new_key:  # Skip fields that don't map
                mapped_updates[new_key] = v

        query = """
        mutation UpdateSchedule($id: uuid!, $set: tasks_set_input!) {
            update_tasks_by_pk(pk_columns: {id: $id}, _set: $set) {
                id user_phone title description status priority
                remind_at due_date completed_at accountability metadata
                created_at updated_at
            }
        }
        """
        data = await self._execute(query, {"id": schedule_id, "set": mapped_updates})
        result = data.get("update_tasks_by_pk")
        if result:
            return Schedule(
                id=result.get("id"),
                phone_number=result.get("user_phone"),
                call_time=result.get("remind_at"),
                context=result.get("title"),
                call_status=result.get("status"),
                created_at=result.get("created_at"),
                updated_at=result.get("updated_at"),
            )
        return None

    async def delete_schedules(self, phone: str) -> int:
        query = """
        mutation DeleteSchedules($phone: String!) {
            delete_tasks(where: {user_phone: {_eq: $phone}}) {
                affected_rows
            }
        }
        """
        data = await self._execute(query, {"phone": phone})
        return data.get("delete_tasks", {}).get("affected_rows", 0)

    async def get_due_schedules(self, before: datetime) -> List[Schedule]:
        query = """
        query GetDueSchedules($before: timestamptz!) {
            tasks(
                where: {
                    remind_at: {_lte: $before},
                    status: {_eq: "pending"}
                },
                order_by: {remind_at: asc}
            ) {
                id user_phone title description status priority
                remind_at due_date completed_at accountability metadata
                created_at updated_at
            }
        }
        """
        data = await self._execute(query, {"before": before.isoformat()})

        schedules = []
        for t in data.get("tasks", []):
            acc = t.get("accountability") or {}
            schedules.append(Schedule(
                id=t.get("id"),
                phone_number=t.get("user_phone"),
                call_time=t.get("remind_at"),
                context=t.get("title"),
                call_status=t.get("status"),
                reminder_sent=False,
                follow_up_count=acc.get("reminder_count", 0),
                created_at=t.get("created_at"),
                updated_at=t.get("updated_at"),
            ))
        return schedules

    # Chat operations - using conversations table (v2)
    async def save_chat(self, chat: Chat) -> Chat:
        query = """
        mutation SaveChat($object: conversations_insert_input!) {
            insert_conversations_one(object: $object) {
                id user_phone direction message timestamp
            }
        }
        """
        # Map chat type to direction (code uses "received"/"sent")
        direction = "incoming" if chat.type == "received" else "outgoing"
        obj = {
            "user_phone": chat.phone_no,
            "message": chat.chat,
            "direction": direction,
        }
        data = await self._execute(query, {"object": obj})
        c = data["insert_conversations_one"]
        return Chat(
            id=c.get("id"),
            phone_no=c.get("user_phone"),
            chat=c.get("message"),
            type="user" if c.get("direction") == "incoming" else "donna",
            created_at=c.get("timestamp"),
        )

    async def get_chats(self, phone: str, limit: int = 20) -> List[Chat]:
        query = """
        query GetChats($phone: String!, $limit: Int!) {
            conversations(
                where: {user_phone: {_eq: $phone}},
                order_by: {timestamp: desc},
                limit: $limit
            ) {
                id user_phone direction message timestamp
            }
        }
        """
        data = await self._execute(query, {"phone": phone, "limit": limit})
        # Reverse to get chronological order
        convs = data.get("conversations", [])
        chats = []
        for c in reversed(convs):
            chats.append(Chat(
                id=c.get("id"),
                phone_no=c.get("user_phone"),
                chat=c.get("message"),
                type="user" if c.get("direction") == "incoming" else "donna",
                created_at=c.get("timestamp"),
            ))
        return chats

    async def delete_chats(self, phone: str) -> int:
        query = """
        mutation DeleteChats($phone: String!) {
            delete_conversations(where: {user_phone: {_eq: $phone}}) {
                affected_rows
            }
        }
        """
        data = await self._execute(query, {"phone": phone})
        return data.get("delete_conversations", {}).get("affected_rows", 0)

    # Entity operations (people, places, things)
    async def upsert_entity(
        self, phone: str, entity_type: str, name: str, attributes: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Create or update an entity."""
        query = """
        mutation UpsertEntity($object: entities_insert_input!, $update_cols: [entities_update_column!]!) {
            insert_entities_one(
                object: $object,
                on_conflict: {
                    constraint: entities_user_phone_type_name_key,
                    update_columns: $update_cols
                }
            ) {
                id user_phone type name attributes last_mentioned mention_count created_at
            }
        }
        """
        obj = {
            "user_phone": phone,
            "type": entity_type,
            "name": name,
            "attributes": attributes,
            "last_mentioned": datetime.utcnow().isoformat(),
        }
        try:
            data = await self._execute(query, {
                "object": obj,
                "update_cols": ["attributes", "last_mentioned", "mention_count"]
            })
            return data.get("insert_entities_one", {})
        except Exception as e:
            logger.error(f"Failed to upsert entity: {e}")
            return {}

    async def get_entities(
        self, phone: str, entity_type: Optional[str] = None, name: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Get entities for a user."""
        where_parts = ["user_phone: {_eq: $phone}"]
        variables = {"phone": phone}

        if entity_type:
            where_parts.append("type: {_eq: $type}")
            variables["type"] = entity_type

        if name:
            where_parts.append("name: {_ilike: $name}")
            variables["name"] = f"%{name}%"

        where_clause = "{" + ", ".join(where_parts) + "}"

        query = f"""
        query GetEntities($phone: String!, $type: String, $name: String) {{
            entities(
                where: {where_clause},
                order_by: {{last_mentioned: desc}},
                limit: 20
            ) {{
                id user_phone type name attributes last_mentioned mention_count created_at
            }}
        }}
        """
        try:
            data = await self._execute(query, variables)
            return data.get("entities", [])
        except Exception as e:
            logger.error(f"Failed to get entities: {e}")
            return []

    # Memory operations
    async def save_memory(
        self, phone: str, category: str, content: str,
        pinecone_id: Optional[str] = None, importance: float = 0.5
    ) -> Dict[str, Any]:
        """Save a memory record."""
        query = """
        mutation SaveMemory($object: memories_insert_input!) {
            insert_memories_one(object: $object) {
                id user_phone pinecone_id category content importance created_at
            }
        }
        """
        obj = {
            "user_phone": phone,
            "category": category,
            "content": content,
            "pinecone_id": pinecone_id,
            "importance": importance,
            "source_type": "conversation",
        }
        try:
            data = await self._execute(query, {"object": obj})
            return data.get("insert_memories_one", {})
        except Exception as e:
            logger.error(f"Failed to save memory: {e}")
            return {}

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
