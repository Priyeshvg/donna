"""Vector memory integration with Pinecone for Donna AI."""

from .client import MemoryClient, get_memory_client
from .extractor import extract_memories

__all__ = ["MemoryClient", "get_memory_client", "extract_memories"]
