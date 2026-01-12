"""LLM client supporting both OpenRouter and AWS Bedrock.

Features:
- Prompt caching for Claude models (90% cost reduction, 85% latency reduction)
- Haiku for simple messages (10x faster)
- Retry logic with exponential backoff
"""

from __future__ import annotations

import os
import json
import hashlib
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple

import httpx

from ...logging_config import logger


# Simple message patterns that can use Haiku (faster, cheaper)
SIMPLE_PATTERNS = {
    "hi", "hello", "hey", "yo", "sup", "thanks", "thank you", "thx",
    "ok", "okay", "bye", "yes", "no", "sure", "cool", "nice", "great",
    "good", "fine", "yep", "nope", "yeah", "yea", "nah", "k", "kk",
    "morning", "night", "gm", "gn", "haha", "lol", "hehe",
}


def is_simple_message(message: str) -> bool:
    """Check if message is simple enough for Haiku."""
    msg = message.lower().strip().rstrip("!?.,'\"")
    return len(msg) < 20 and msg in SIMPLE_PATTERNS


class LLMClient(ABC):
    """Abstract LLM client interface."""

    @abstractmethod
    async def chat_completion(
        self,
        messages: List[Dict[str, Any]],
        system: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        model: Optional[str] = None,
        use_cache: bool = True,
    ) -> Dict[str, Any]:
        """Generate a chat completion."""
        pass


class OpenRouterClient(LLMClient):
    """OpenRouter API client with prompt caching support."""

    MAX_RETRIES = 2
    RETRY_DELAY = 1.0  # seconds

    # Models
    SONNET_MODEL = "anthropic/claude-sonnet-4"
    HAIKU_MODEL = "anthropic/claude-3-5-haiku"

    def __init__(self, api_key: str, default_model: str = "anthropic/claude-sonnet-4"):
        self.api_key = api_key
        self.default_model = default_model
        self.base_url = "https://openrouter.ai/api/v1"
        self._client = httpx.AsyncClient(timeout=120.0)

    def _build_system_with_cache(self, system: str) -> List[Dict[str, Any]]:
        """Build system message with cache_control for prompt caching.

        This caches the system prompt so subsequent requests don't need to
        reprocess it. Saves up to 90% on input tokens and 85% latency.
        """
        return [
            {
                "type": "text",
                "text": system,
                "cache_control": {"type": "ephemeral"}  # 5-minute cache
            }
        ]

    async def chat_completion(
        self,
        messages: List[Dict[str, Any]],
        system: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        model: Optional[str] = None,
        use_cache: bool = True,
    ) -> Dict[str, Any]:
        """Call OpenRouter API with prompt caching and retry logic.

        Args:
            messages: Chat messages
            system: System prompt (will be cached if use_cache=True)
            tools: Tool definitions
            model: Model override (None = auto-select based on message complexity)
            use_cache: Whether to use prompt caching (default True)
        """
        import asyncio

        # Auto-select model based on message complexity
        if model is None:
            last_user_msg = ""
            for msg in reversed(messages):
                if msg.get("role") == "user":
                    content = msg.get("content", "")
                    if isinstance(content, str):
                        last_user_msg = content
                    break

            # Use Haiku for simple messages (10x faster, much cheaper)
            if is_simple_message(last_user_msg) and not tools:
                model = self.HAIKU_MODEL
                logger.info(f"Using Haiku for simple message: {last_user_msg[:30]}")
            else:
                model = self.default_model

        # Build payload
        payload: Dict[str, Any] = {
            "model": model,
            "messages": [],
        }

        # Add system prompt with caching
        if system:
            if use_cache and "anthropic" in model:
                # Use Anthropic-style system with cache_control
                payload["messages"].append({
                    "role": "system",
                    "content": self._build_system_with_cache(system)
                })
            else:
                payload["messages"].append({
                    "role": "system",
                    "content": system
                })

        # Add conversation messages
        payload["messages"].extend(messages)

        if tools:
            payload["tools"] = tools

        # Make request with retries
        last_error = None
        for attempt in range(self.MAX_RETRIES + 1):
            try:
                response = await self._client.post(
                    f"{self.base_url}/chat/completions",
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                )
                response.raise_for_status()
                result = response.json()

                # Log cache usage if available
                usage = result.get("usage", {})
                if usage.get("cache_read_input_tokens"):
                    logger.info(f"Cache hit! Read {usage['cache_read_input_tokens']} cached tokens")

                return result
            except (httpx.TimeoutException, httpx.HTTPStatusError) as e:
                last_error = e
                if attempt < self.MAX_RETRIES:
                    logger.warning(f"LLM call failed (attempt {attempt + 1}), retrying: {e}")
                    await asyncio.sleep(self.RETRY_DELAY * (attempt + 1))
                else:
                    logger.error(f"LLM call failed after {self.MAX_RETRIES + 1} attempts: {e}")
                    raise

        raise last_error


class BedrockClient(LLMClient):
    """AWS Bedrock client using Claude models."""

    def __init__(
        self,
        aws_access_key: str,
        aws_secret_key: str,
        aws_region: str = "us-east-1",
        default_model: str = "anthropic.claude-3-5-sonnet-20241022-v2:0",
    ):
        self.aws_access_key = aws_access_key
        self.aws_secret_key = aws_secret_key
        self.aws_region = aws_region
        self.default_model = default_model

        try:
            import boto3
            self.client = boto3.client(
                "bedrock-runtime",
                region_name=aws_region,
                aws_access_key_id=aws_access_key,
                aws_secret_access_key=aws_secret_key,
            )
            self._available = True
        except ImportError:
            logger.warning("boto3 not installed - Bedrock unavailable")
            self._available = False

    async def chat_completion(
        self,
        messages: List[Dict[str, Any]],
        system: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        model: Optional[str] = None,
        use_cache: bool = True,
    ) -> Dict[str, Any]:
        """Call AWS Bedrock with Claude."""
        if not self._available:
            raise RuntimeError("boto3 required for Bedrock")

        model = model or self.default_model

        # Convert to Bedrock/Claude format
        bedrock_messages = []
        for msg in messages:
            role = msg["role"]
            content = msg["content"]

            # Handle tool results
            if role == "tool":
                bedrock_messages.append({
                    "role": "user",
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": msg.get("tool_call_id", ""),
                        "content": content
                    }]
                })
            elif role == "assistant" and msg.get("tool_calls"):
                # Assistant message with tool calls
                tool_use_blocks = []
                for tc in msg["tool_calls"]:
                    tool_use_blocks.append({
                        "type": "tool_use",
                        "id": tc["id"],
                        "name": tc["function"]["name"],
                        "input": json.loads(tc["function"]["arguments"])
                    })
                bedrock_messages.append({
                    "role": "assistant",
                    "content": tool_use_blocks
                })
            else:
                bedrock_messages.append({
                    "role": role,
                    "content": content
                })

        # Build request body
        body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 4096,
            "messages": bedrock_messages,
        }

        if system:
            body["system"] = system

        if tools:
            # Convert OpenAI tool format to Bedrock/Claude format
            bedrock_tools = []
            for tool in tools:
                if tool.get("type") == "function":
                    func = tool["function"]
                    bedrock_tools.append({
                        "name": func["name"],
                        "description": func.get("description", ""),
                        "input_schema": func.get("parameters", {"type": "object", "properties": {}})
                    })
            body["tools"] = bedrock_tools

        # Call Bedrock (sync, but we're in async context - use run_in_executor if needed)
        import asyncio
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: self.client.invoke_model(
                modelId=model,
                body=json.dumps(body),
                contentType="application/json",
                accept="application/json",
            )
        )

        result = json.loads(response["body"].read())

        # Convert Bedrock response to OpenAI-like format
        return self._convert_response(result)

    def _convert_response(self, bedrock_response: Dict[str, Any]) -> Dict[str, Any]:
        """Convert Bedrock response to OpenAI-like format."""
        content = bedrock_response.get("content", [])
        stop_reason = bedrock_response.get("stop_reason", "end_turn")

        # Check for tool use
        tool_calls = []
        text_content = ""

        for block in content:
            if block.get("type") == "tool_use":
                tool_calls.append({
                    "id": block["id"],
                    "type": "function",
                    "function": {
                        "name": block["name"],
                        "arguments": json.dumps(block["input"])
                    }
                })
            elif block.get("type") == "text":
                text_content = block.get("text", "")

        # Build OpenAI-like response
        message = {
            "role": "assistant",
            "content": text_content if text_content else None,
        }

        if tool_calls:
            message["tool_calls"] = tool_calls

        finish_reason = "tool_calls" if stop_reason == "tool_use" else "stop"

        return {
            "choices": [{
                "message": message,
                "finish_reason": finish_reason,
            }],
            "usage": bedrock_response.get("usage", {})
        }


# Singleton instance
_llm_client: Optional[LLMClient] = None


def get_llm_client() -> LLMClient:
    """Get the singleton LLM client."""
    global _llm_client

    if _llm_client is None:
        # Check for AWS Bedrock first
        aws_access_key = os.getenv("AWS_ACCESS_KEY_ID")
        aws_secret_key = os.getenv("AWS_SECRET_ACCESS_KEY")
        aws_region = os.getenv("AWS_REGION", "us-east-1")

        if aws_access_key and aws_secret_key:
            logger.info(f"Using AWS Bedrock (region: {aws_region})")
            default_model = os.getenv("BEDROCK_MODEL", "anthropic.claude-3-5-sonnet-20241022-v2:0")
            _llm_client = BedrockClient(
                aws_access_key=aws_access_key,
                aws_secret_key=aws_secret_key,
                aws_region=aws_region,
                default_model=default_model,
            )
        else:
            # Fall back to OpenRouter
            openrouter_key = os.getenv("OPENROUTER_API_KEY")
            if not openrouter_key:
                raise ValueError("No LLM configured. Set AWS credentials or OPENROUTER_API_KEY")

            # Use Sonnet by default for accuracy, can override with OPENROUTER_MODEL
            default_model = os.getenv("OPENROUTER_MODEL", "anthropic/claude-sonnet-4")
            logger.info(f"Using OpenRouter with model: {default_model}")
            _llm_client = OpenRouterClient(
                api_key=openrouter_key,
                default_model=default_model,
            )

    return _llm_client


__all__ = ["LLMClient", "get_llm_client", "OpenRouterClient", "BedrockClient"]
