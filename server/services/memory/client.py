"""Pinecone vector memory client for Donna AI."""

from __future__ import annotations

import os
import uuid
from typing import Any, Dict, List, Optional
from functools import lru_cache

import httpx

from ...logging_config import logger


class MemoryClient:
    """Client for Pinecone vector memory operations."""

    MAX_RETRIES = 2
    RETRY_DELAY = 0.5  # seconds

    def __init__(
        self,
        api_key: str,
        index_name: str,
        host: Optional[str] = None,
    ):
        self.api_key = api_key
        self.index_name = index_name
        # Pinecone serverless uses host from index describe or env var
        self.base_url = host or os.getenv("PINECONE_HOST", "")
        self._client = httpx.AsyncClient(timeout=30.0)
        self._embedding_client = httpx.AsyncClient(timeout=60.0)
        self._host_resolved = bool(self.base_url)

    async def _ensure_host(self) -> bool:
        """Resolve Pinecone host if not already set."""
        if self._host_resolved:
            return True

        try:
            # Get index host from Pinecone API
            response = await self._client.get(
                f"https://api.pinecone.io/indexes/{self.index_name}",
                headers={"Api-Key": self.api_key},
            )
            response.raise_for_status()
            data = response.json()
            self.base_url = f"https://{data['host']}"
            self._host_resolved = True
            logger.info(f"Resolved Pinecone host: {self.base_url}")
            return True
        except Exception as e:
            logger.error(f"Failed to resolve Pinecone host: {e}")
            return False

    async def _get_embedding(self, text: str) -> List[float]:
        """Get embedding from OpenRouter with retry logic."""
        import asyncio

        openrouter_key = os.getenv("OPENROUTER_API_KEY")
        if not openrouter_key:
            raise ValueError("OPENROUTER_API_KEY required for embeddings")

        last_error = None
        for attempt in range(self.MAX_RETRIES + 1):
            try:
                response = await self._embedding_client.post(
                    "https://openrouter.ai/api/v1/embeddings",
                    json={
                        "model": "openai/text-embedding-3-small",
                        "input": text,
                        "dimensions": 1024,  # Match Pinecone index dimension
                    },
                    headers={
                        "Authorization": f"Bearer {openrouter_key}",
                        "Content-Type": "application/json",
                    },
                )
                response.raise_for_status()
                data = response.json()
                return data["data"][0]["embedding"]
            except (httpx.TimeoutException, httpx.HTTPStatusError) as e:
                last_error = e
                if attempt < self.MAX_RETRIES:
                    logger.warning(f"Embedding call failed (attempt {attempt + 1}), retrying: {e}")
                    await asyncio.sleep(self.RETRY_DELAY * (attempt + 1))
                else:
                    logger.error(f"Embedding call failed after {self.MAX_RETRIES + 1} attempts: {e}")
                    raise

        raise last_error

    # Standard memory categories
    CATEGORIES = {
        "contact": ["number", "phone", "email", "address", "mobile"],
        "event": ["birthday", "anniversary", "meeting", "appointment"],
        "preference": ["prefers", "likes", "dislikes", "wants", "favorite", "loves"],
        "relationship": ["is my", "are my", "wife", "husband", "friend", "colleague", "boss", "girlfriend", "boyfriend"],
        "fact": [],  # Default category
    }

    # Categories that should deduplicate (same entity+category+type = same vector)
    # Empty set = all categories allow multiple vectors per entity
    # Deduplication now happens at content level (same content = same vector)
    DEDUPE_CATEGORIES = set()  # No automatic deduping - allow multiple of everything

    # Temporal keywords for detecting current vs old information
    TEMPORAL_CURRENT = ["new", "current", "now", "updated", "latest", "changed to"]
    TEMPORAL_OLD = ["old", "previous", "former", "was", "used to be", "no longer"]

    def _detect_temporal_status(self, content: str) -> Optional[bool]:
        """Detect if content refers to current or old information.

        Returns:
            True if current/new, False if old/previous, None if not specified
        """
        content_lower = content.lower()

        for keyword in self.TEMPORAL_CURRENT:
            if keyword in content_lower:
                return True

        for keyword in self.TEMPORAL_OLD:
            if keyword in content_lower:
                return False

        return None  # No temporal indicator

    def _detect_category(self, content: str) -> str:
        """Detect the memory category from content."""
        content_lower = content.lower()

        for category, keywords in self.CATEGORIES.items():
            for keyword in keywords:
                if keyword in content_lower:
                    return category

        return "fact"

    def _extract_entity(self, content: str) -> Optional[str]:
        """Extract the main entity (person/thing) from content."""
        import re

        content_lower = content.lower()

        # Patterns to extract entity names
        patterns = [
            r"(\w+)'s\s+(number|phone|birthday|email|address)",  # "Purvi's phone"
            r"(\w+)\s+(number|phone|birthday|email)\s+is",  # "Purvi phone is"
            r"(my\s+\w+)'s",  # "my mom's birthday"
            r"^(\w+)\s+is\s+",  # "Akash is my friend"
            r"^(\w+)\s+(loves?|likes?|prefers?|wants?|hates?|dislikes?)\s+",  # "Purvi loves waffles"
            r"^(\w+)\s+(favorite|favourite)\s+",  # "Purvi favorite color"
        ]

        for pattern in patterns:
            match = re.search(pattern, content_lower)
            if match:
                return match.group(1).strip()

        return None

    def _generate_semantic_id(self, phone: str, content: str, metadata: Optional[Dict[str, Any]]) -> str:
        """Generate an ID for vector storage with content-based deduplication.

        Deduplication is based on content similarity:
        - Same/very similar content about same entity = same vector (updates)
        - Different content about same entity = different vectors (allows multiple)

        This allows storing multiple items per entity:
        - "Purvi's work phone is 123" + "Purvi's personal phone is 456" = 2 vectors
        - "Purvi is my girlfriend" + "Purvi is my wife" = 2 vectors
        - "Purvi's birthday is March 15" + "Purvi's anniversary is June 20" = 2 vectors

        But prevents true duplicates:
        - "Purvi loves waffles" stored twice = 1 vector (same content = same ID)
        """
        import hashlib

        meta = metadata or {}

        # Use metadata entity if provided, otherwise extract from content
        entity = meta.get("person") or meta.get("entity") or self._extract_entity(content)

        # Use metadata category if provided, otherwise detect from content
        category = meta.get("category") or self._detect_category(content)

        # Generate content-based hash for deduplication
        # Same content = same ID (prevents duplicates)
        # Different content = different ID (allows multiple per entity)
        content_normalized = content.lower().strip()
        content_hash = hashlib.md5(content_normalized.encode()).hexdigest()[:12]

        if entity:
            entity = entity.lower()
            # Include entity and category for better organization
            key = f"{phone}:{entity}:{category}:{content_hash}"
        else:
            # No entity found, use phone + category + content
            key = f"{phone}:{category}:{content_hash}"

        return hashlib.md5(key.encode()).hexdigest()

    async def store(
        self,
        phone: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Store content in vector memory for a user.

        Uses smart deduplication: if content is about the same entity
        (e.g., "Akash's number"), it updates the existing vector instead
        of creating a duplicate.

        Args:
            phone: User's phone number (used as namespace)
            content: Text content to store
            metadata: Additional metadata

        Returns:
            Vector ID
        """
        try:
            # Ensure host is resolved
            if not await self._ensure_host():
                raise ValueError("Could not resolve Pinecone host")

            # Generate embedding
            embedding = await self._get_embedding(content)

            # Generate semantic ID (deterministic for same entity)
            vector_id = self._generate_semantic_id(phone, content, metadata)

            # Prepare metadata with auto-detected category and entity
            meta = metadata or {}
            meta["phone"] = phone
            meta["content"] = content[:1000]  # Store truncated content in metadata
            meta["updated_at"] = __import__('datetime').datetime.now().isoformat()

            # Auto-detect and add category/entity if not provided
            if "category" not in meta:
                meta["category"] = self._detect_category(content)
            if "entity" not in meta:
                entity = self._extract_entity(content)
                if entity:
                    meta["entity"] = entity

            # Auto-detect temporal status (is_current)
            # True = current/new, False = old/previous, not set = unspecified
            if "is_current" not in meta:
                temporal_status = self._detect_temporal_status(content)
                if temporal_status is not None:
                    meta["is_current"] = temporal_status

            # Upsert to Pinecone (will update if ID exists)
            response = await self._client.post(
                f"{self.base_url}/vectors/upsert",
                json={
                    "vectors": [
                        {
                            "id": vector_id,
                            "values": embedding,
                            "metadata": meta,
                        }
                    ],
                    "namespace": phone,
                },
                headers={
                    "Api-Key": self.api_key,
                    "Content-Type": "application/json",
                },
            )
            response.raise_for_status()
            logger.info(f"Stored/updated memory for {phone} (id={vector_id[:8]}...): {content[:50]}...")
            return vector_id

        except Exception as e:
            logger.error(f"Failed to store memory: {e}")
            raise

    async def search(
        self,
        phone: str,
        query: str,
        top_k: int = 10,
        current_only: bool = False,
    ) -> List[Dict[str, Any]]:
        """Search vector memory for relevant content.

        Args:
            phone: User's phone number (namespace)
            query: Search query
            top_k: Number of results to return
            current_only: If True, filter out results marked as old/previous

        Returns:
            List of matching memories with scores, sorted by relevance
            (current items are boosted in ranking)
        """
        try:
            # Ensure host is resolved
            if not await self._ensure_host():
                return []

            # Generate query embedding
            embedding = await self._get_embedding(query)

            # Query Pinecone (fetch extra if filtering)
            fetch_k = top_k * 2 if current_only else top_k

            # Query Pinecone
            response = await self._client.post(
                f"{self.base_url}/query",
                json={
                    "vector": embedding,
                    "topK": fetch_k,
                    "includeMetadata": True,
                    "namespace": phone,
                },
                headers={
                    "Api-Key": self.api_key,
                    "Content-Type": "application/json",
                },
            )
            response.raise_for_status()
            data = response.json()

            results = []
            for match in data.get("matches", []):
                metadata = match.get("metadata", {})
                # Support both 'content' (new) and 'text' (legacy) fields
                content = metadata.get("content") or metadata.get("text", "")

                # Check temporal status
                is_current = metadata.get("is_current")

                # Skip old items if current_only is requested
                if current_only and is_current is False:
                    continue

                # Calculate adjusted score (boost current items)
                base_score = match["score"]
                if is_current is True:
                    adjusted_score = base_score * 1.1  # 10% boost for current
                elif is_current is False:
                    adjusted_score = base_score * 0.9  # 10% penalty for old
                else:
                    adjusted_score = base_score

                results.append({
                    "id": match["id"],
                    "score": base_score,
                    "adjusted_score": adjusted_score,
                    "content": content,
                    "is_current": is_current,
                    "metadata": metadata,
                })

            # Sort by adjusted score and limit to top_k
            results.sort(key=lambda x: x["adjusted_score"], reverse=True)
            results = results[:top_k]

            logger.info(f"Found {len(results)} memories for query: {query[:50]}...")
            return results

        except Exception as e:
            logger.error(f"Failed to search memory: {e}")
            return []

    async def delete_namespace(self, phone: str) -> bool:
        """Delete all vectors for a user (used in reset).

        Args:
            phone: User's phone number (namespace)

        Returns:
            Success status
        """
        try:
            # Ensure host is resolved
            if not await self._ensure_host():
                return False

            response = await self._client.post(
                f"{self.base_url}/vectors/delete",
                json={
                    "deleteAll": True,
                    "namespace": phone,
                },
                headers={
                    "Api-Key": self.api_key,
                    "Content-Type": "application/json",
                },
            )
            response.raise_for_status()
            logger.info(f"Deleted memory namespace for {phone}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete namespace: {e}")
            return False


# Singleton instance
_memory_client: Optional[MemoryClient] = None


def get_memory_client() -> Optional[MemoryClient]:
    """Get the singleton memory client. Returns None if not configured."""
    global _memory_client
    if _memory_client is None:
        api_key = os.getenv("PINECONE_API_KEY")
        index_name = os.getenv("PINECONE_INDEX", "donna-memory")

        if not api_key:
            logger.warning("Pinecone not configured - memory features disabled")
            return None

        _memory_client = MemoryClient(api_key, index_name)

    return _memory_client


__all__ = ["MemoryClient", "get_memory_client"]
