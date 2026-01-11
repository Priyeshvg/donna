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
        environment: str = "us-east-1",
    ):
        self.api_key = api_key
        self.index_name = index_name
        self.environment = environment
        # Pinecone serverless endpoint format
        self.base_url = f"https://{index_name}-{environment}.svc.pinecone.io"
        self._client = httpx.AsyncClient(timeout=30.0)
        self._embedding_client = httpx.AsyncClient(timeout=60.0)

    async def _get_embedding(self, text: str) -> List[float]:
        """Get embedding from OpenRouter (uses OpenAI-compatible endpoint)."""
        openrouter_key = os.getenv("OPENROUTER_API_KEY")
        if not openrouter_key:
            raise ValueError("OPENROUTER_API_KEY required for embeddings")

        # Use OpenRouter's embedding endpoint
        response = await self._embedding_client.post(
            "https://openrouter.ai/api/v1/embeddings",
            json={
                "model": "openai/text-embedding-3-small",
                "input": text,
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
                results.append({
                    "id": match["id"],
                    "score": match["score"],
                    "content": match.get("metadata", {}).get("content", ""),
                    "metadata": match.get("metadata", {}),
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
