"""LLM client abstraction - supports OpenRouter and AWS Bedrock."""

from .client import get_llm_client, LLMClient

__all__ = ["get_llm_client", "LLMClient"]
