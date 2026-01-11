"""LLM client supporting both OpenRouter and AWS Bedrock."""

from __future__ import annotations

import os
import json
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

import httpx

from ...logging_config import logger


class LLMClient(ABC):
    """Abstract LLM client interface."""

    @abstractmethod
    async def chat_completion(
        self,
        messages: List[Dict[str, Any]],
        system: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        model: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Generate a chat completion."""
        pass


class OpenRouterClient(LLMClient):
    """OpenRouter API client."""

    def __init__(self, api_key: str, default_model: str = "anthropic/claude-3.5-haiku"):
        self.api_key = api_key
        self.default_model = default_model
        self.base_url = "https://openrouter.ai/api/v1"
        self._client = httpx.AsyncClient(timeout=60.0)

    async def chat_completion(
        self,
        messages: List[Dict[str, Any]],
        system: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        model: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Call OpenRouter API."""
        model = model or self.default_model

        # Prepend system message if provided
        if system:
            messages = [{"role": "system", "content": system}] + messages

        payload = {
            "model": model,
            "messages": messages,
        }
        if tools:
            payload["tools"] = tools

        response = await self._client.post(
            f"{self.base_url}/chat/completions",
            json=payload,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )
        response.raise_for_status()
        return response.json()


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

            # Use Haiku by default for speed, can override with OPENROUTER_MODEL
            default_model = os.getenv("OPENROUTER_MODEL", "anthropic/claude-3.5-haiku")
            logger.info(f"Using OpenRouter with model: {default_model}")
            _llm_client = OpenRouterClient(
                api_key=openrouter_key,
                default_model=default_model,
            )

    return _llm_client


__all__ = ["LLMClient", "get_llm_client", "OpenRouterClient", "BedrockClient"]
