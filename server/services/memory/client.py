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
        """Get embedding from OpenRouter (uses OpenAI-compatible endpoint)."""
        openrouter_key = os.getenv("OPENROUTER_API_KEY")
        if not openrouter_key:
            raise ValueError("OPENROUTER_API_KEY required for embeddings")

        # Use OpenRouter's embedding endpoint
        # IMPORTANT: Pinecone index is 1024 dimensions, so we must specify dimensions=1024
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

    async def store(
        self,
        phone: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Store content in vector memory for a user.

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

            # Create vector ID
            vector_id = str(uuid.uuid4())

            # Prepare metadata
            meta = metadata or {}
            meta["phone"] = phone
            meta["content"] = content[:1000]  # Store truncated content in metadata

            # Upsert to Pinecone
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
            logger.info(f"Stored memory for {phone}: {content[:50]}...")
            return vector_id

        except Exception as e:
            logger.error(f"Failed to store memory: {e}")
            raise

    async def search(
        self,
        phone: str,
        query: str,
        top_k: int = 10,
    ) -> List[Dict[str, Any]]:
        """Search vector memory for relevant content.

        Args:
            phone: User's phone number (namespace)
            query: Search query
            top_k: Number of results to return

        Returns:
            List of matching memories with scores
        """
        try:
            # Ensure host is resolved
            if not await self._ensure_host():
                return []

            # Generate query embedding
            embedding = await self._get_embedding(query)

            # Query Pinecone
            response = await self._client.post(
                f"{self.base_url}/query",
                json={
                    "vector": embedding,
                    "topK": top_k,
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
                results.append({
                    "id": match["id"],
                    "score": match["score"],
                    "content": content,
                    "metadata": metadata,
                })

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
