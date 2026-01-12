"""Memory extraction service.

Extracts entities, facts, and preferences from conversations
and stores them in Postgres + Pinecone for future retrieval.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional
from uuid import uuid4

from ..llm import get_llm_client
from ..database import get_database_client
from . import get_memory_client
from ...logging_config import logger


EXTRACTION_PROMPT = """Analyze this conversation and extract important information to remember about the user.

Return a JSON object with:
1. "entities": Array of people, places, or things mentioned
   - Each entity: {"type": "person|place|organization|thing", "name": "...", "attributes": {...}}
   - For people: include phone, email, relationship if mentioned
   - Example: {"type": "person", "name": "Akash", "attributes": {"phone": "9876543210", "relationship": "friend"}}

2. "facts": Array of factual statements about the user
   - Things that are true about them
   - Example: "Works at Google", "Lives in Mumbai"

3. "preferences": Array of user preferences
   - Likes, dislikes, habits
   - Example: "Prefers morning meetings", "Doesn't like email"

Only include information explicitly stated or clearly implied. Don't make assumptions.
If nothing notable to extract, return empty arrays.

Respond with ONLY valid JSON, no explanation."""


async def extract_memories(
    phone: str,
    messages: List[Dict[str, str]],
    run_async: bool = True
) -> Optional[Dict[str, Any]]:
    """Extract and store memories from a conversation.

    Args:
        phone: User's phone number
        messages: List of messages in the conversation
        run_async: If True, doesn't wait for completion (fire and forget)

    Returns:
        Extraction result if run_async=False, else None
    """
    if not messages or len(messages) < 2:
        return None  # Need at least 2 messages

    try:
        llm = get_llm_client()
        db = get_database_client()
        memory = get_memory_client()

        # Build conversation text
        conversation_text = "\n".join([
            f"{'User' if m['role'] == 'user' else 'Assistant'}: {m['content']}"
            for m in messages[-10:]  # Last 10 messages
        ])

        # Ask LLM to extract memories
        response = await llm.chat_completion(
            messages=[{"role": "user", "content": f"Conversation:\n{conversation_text}"}],
            system=EXTRACTION_PROMPT,
            model="anthropic/claude-3-5-haiku",  # Use Haiku for extraction (fast, cheap)
            use_cache=False,  # Don't cache extraction prompts
        )

        content = response.get("choices", [{}])[0].get("message", {}).get("content", "")

        # Parse JSON response
        try:
            extraction = json.loads(content)
        except json.JSONDecodeError:
            # Try to extract JSON from response
            import re
            json_match = re.search(r'\{[\s\S]*\}', content)
            if json_match:
                extraction = json.loads(json_match.group())
            else:
                logger.warning(f"Failed to parse extraction response: {content[:100]}")
                return None

        entities = extraction.get("entities", [])
        facts = extraction.get("facts", [])
        preferences = extraction.get("preferences", [])

        # Store entities in Postgres
        for entity in entities:
            entity_type = entity.get("type", "thing")
            name = entity.get("name", "")
            attributes = entity.get("attributes", {})

            if name:
                await db.upsert_entity(phone, entity_type, name, attributes)
                logger.info(f"Stored entity: {entity_type}/{name}")

        # Store facts and preferences in Pinecone
        if memory:
            for fact in facts:
                if fact and isinstance(fact, str):
                    vector_id = f"fact_{uuid4().hex[:8]}"
                    await memory.add_memory(
                        phone=phone,
                        content=fact,
                        category="fact",
                        metadata={"source": "extraction"}
                    )
                    await db.save_memory(phone, "fact", fact, vector_id, importance=0.6)

            for pref in preferences:
                if pref and isinstance(pref, str):
                    vector_id = f"pref_{uuid4().hex[:8]}"
                    await memory.add_memory(
                        phone=phone,
                        content=pref,
                        category="preference",
                        metadata={"source": "extraction"}
                    )
                    await db.save_memory(phone, "preference", pref, vector_id, importance=0.7)

        result = {
            "entities_stored": len(entities),
            "facts_stored": len(facts),
            "preferences_stored": len(preferences),
        }

        logger.info(f"Memory extraction complete: {result}")
        return result

    except Exception as e:
        logger.error(f"Memory extraction failed: {e}")
        return None


__all__ = ["extract_memories"]
