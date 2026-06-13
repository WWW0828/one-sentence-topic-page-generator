import os
import asyncio
import json
import logging
import anthropic
from google import genai
from google.genai import types
from pydantic import BaseModel

from schemas.topic_page import ClassificationResult
from config import call_with_fallback, gemini_client, anthropic_client

logger = logging.getLogger(__name__)

QUERY_GEN_PROMPT = """You are generating web search queries to research a news event for a topic page.

Event: "{sentence}"
Type: {event_type}
Key entities: {entities}

Generate 6–8 targeted search queries that together will surface:
- Recent news and current status
- Timeline of key developments
- Key people and organizations involved
- Factual specifics (dates, venues, numbers, statistics)
- Background context

Each query should be focused on a different aspect. Write queries as a search engine user would — short, specific, no filler words."""

class QueryGenResult(BaseModel):
    queries: list[str]


async def generate_search_queries(
    sentence: str,
    classification: ClassificationResult,
    provider: str
) -> list[str]:
    entities_str = ", ".join(e.name for e in classification.entities[:5])
    prompt = QUERY_GEN_PROMPT.format(
        sentence=sentence,
        event_type=classification.event_type.value,
        entities=entities_str
    )

    if provider == "claude":
        return await _query_gen_claude(prompt)
    return await _query_gen_gemini(prompt)


async def _query_gen_claude(prompt: str) -> list[str]:
    client = anthropic_client()

    response = await call_with_fallback("claude", lambda model: client.messages.parse(
        model=model,
        max_tokens=512,
        messages=[{"role": "user", "content": prompt}],
        output_format=QueryGenResult,
    ))

    result = response.parsed_output
    if result is None:
        # Per docs: refusals and max_tokens truncation bypass the schema guarantee.
        logger.error("Claude returned no parseable queries (stop_reason=%s)", response.stop_reason)
        raise ValueError("Claude did not return structured search queries.")
    return result.queries


async def _query_gen_gemini(prompt: str) -> list[str]:
    client = gemini_client()

    loop = asyncio.get_event_loop()
    response = await call_with_fallback("gemini", lambda model: loop.run_in_executor(
        None, lambda: client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=QueryGenResult
            )
        )
    ))

    result = QueryGenResult.model_validate_json(response.text)
    return result.queries
