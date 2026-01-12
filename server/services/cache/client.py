"""Redis cache client for working memory.

Uses Upstash Redis for serverless, low-latency caching.
Provides:
- Session context (last N messages)
- User profile cache
- Active tasks cache
"""

from __future__ import annotations

import os
import json
from typing import Any, Dict, List, Optional
from datetime import timedelta

from ...logging_config import logger


class CacheClient:
    """Redis cache client using Upstash."""

    # TTLs
    SESSION_TTL = timedelta(hours=1)
    USER_TTL = timedelta(minutes=30)
    TASK_TTL = timedelta(minutes=10)

    def __init__(self, redis_url: str):
        self.redis_url = redis_url
        self._client = None
        self._available = False
        self._init_client()

    def _init_client(self):
        """Initialize Redis client."""
        try:
            import redis
            self._client = redis.from_url(
                self.redis_url,
                decode_responses=True,
                socket_timeout=5.0,
                socket_connect_timeout=5.0,
            )
            # Test connection
            self._client.ping()
            self._available = True
            logger.info("Redis cache connected")
        except ImportError:
            logger.warning("redis package not installed - caching disabled")
        except Exception as e:
            logger.warning(f"Redis connection failed: {e} - caching disabled")

    @property
    def available(self) -> bool:
        return self._available

    # Session context (recent messages)
    async def get_session(self, phone: str) -> Optional[Dict[str, Any]]:
        """Get session context for a user."""
        if not self._available:
            return None
        try:
            data = self._client.get(f"session:{phone}")
            return json.loads(data) if data else None
        except Exception as e:
            logger.warning(f"Redis get error: {e}")
            return None

    async def set_session(self, phone: str, session: Dict[str, Any]) -> bool:
        """Store session context."""
        if not self._available:
            return False
        try:
            self._client.setex(
                f"session:{phone}",
                self.SESSION_TTL,
                json.dumps(session)
            )
            return True
        except Exception as e:
            logger.warning(f"Redis set error: {e}")
            return False

    async def update_session_messages(
        self, phone: str, role: str, content: str, max_messages: int = 10
    ) -> bool:
        """Add a message to session and trim to max."""
        if not self._available:
            return False
        try:
            session = await self.get_session(phone) or {"messages": []}
            session["messages"].append({"role": role, "content": content})
            session["messages"] = session["messages"][-max_messages:]
            return await self.set_session(phone, session)
        except Exception as e:
            logger.warning(f"Redis update error: {e}")
            return False

    # User profile cache
    async def get_user(self, phone: str) -> Optional[Dict[str, Any]]:
        """Get cached user profile."""
        if not self._available:
            return None
        try:
            data = self._client.get(f"user:{phone}")
            return json.loads(data) if data else None
        except Exception as e:
            logger.warning(f"Redis get error: {e}")
            return None

    async def set_user(self, phone: str, user: Dict[str, Any]) -> bool:
        """Cache user profile."""
        if not self._available:
            return False
        try:
            self._client.setex(
                f"user:{phone}",
                self.USER_TTL,
                json.dumps(user)
            )
            return True
        except Exception as e:
            logger.warning(f"Redis set error: {e}")
            return False

    # Active tasks cache
    async def get_active_tasks(self, phone: str) -> List[Dict[str, Any]]:
        """Get cached active tasks."""
        if not self._available:
            return []
        try:
            data = self._client.get(f"tasks:{phone}")
            return json.loads(data) if data else []
        except Exception as e:
            logger.warning(f"Redis get error: {e}")
            return []

    async def set_active_tasks(self, phone: str, tasks: List[Dict[str, Any]]) -> bool:
        """Cache active tasks."""
        if not self._available:
            return False
        try:
            self._client.setex(
                f"tasks:{phone}",
                self.TASK_TTL,
                json.dumps(tasks)
            )
            return True
        except Exception as e:
            logger.warning(f"Redis set error: {e}")
            return False

    # Utility
    async def invalidate_user(self, phone: str) -> bool:
        """Invalidate all caches for a user."""
        if not self._available:
            return False
        try:
            self._client.delete(f"session:{phone}", f"user:{phone}", f"tasks:{phone}")
            return True
        except Exception as e:
            logger.warning(f"Redis delete error: {e}")
            return False


# Singleton
_cache_client: Optional[CacheClient] = None


def get_cache_client() -> Optional[CacheClient]:
    """Get the singleton cache client. Returns None if not configured."""
    global _cache_client

    if _cache_client is None:
        redis_url = os.getenv("UPSTASH_REDIS_URL") or os.getenv("REDIS_URL")
        if redis_url:
            _cache_client = CacheClient(redis_url)
        else:
            logger.info("Redis not configured - caching disabled")
            return None

    return _cache_client if _cache_client.available else None


__all__ = ["CacheClient", "get_cache_client"]
