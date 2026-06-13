import os
import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import List
import anthropic
from google import genai
from google.genai import types
from pydantic import BaseModel

logger = logging.getLogger(__name__)

from schemas.topic_page import (
    TopicPage, EventType, ClassificationResult,
    KeyFact, TimelineEntry, Entity, Source,
    SportsData, TechData, CulturalData, BusinessData, DisasterData,
    ScheduleEntry, PlayerStat, FeatureItem, PricingTier, CulturalScheduleEntry,
    LabelValue, CompanyRef, AffectedArea
)
from steps.search import SearchResult
from config import call_with_fallback, gemini_client, anthropic_client


# Shared structured-output models for BOTH providers (Claude messages.parse / Gemini
# response_schema). Flat because Gemini structured output does not support anyOf (used by
# Optional[X] in Pydantic v2).
# KeyFact/TimelineEntry carry Optional/enum fields (note, verification) that are filled by the
# grounding pass, NOT by extraction — so the extract model uses leaner sub-models here.
class _GKeyFact(BaseModel):
    label: str
    value: str
    source_ids: List[int] = []


class _GTimelineEntry(BaseModel):
    date: str
    description: str
    source_ids: List[int] = []


class _BaseExtract(BaseModel):
    title: str
    summary: str
    last_updated: str
    key_facts: List[_GKeyFact] = []
    timeline: List[_GTimelineEntry] = []
    entities: List[Entity] = []
    sources: List[Source] = []


# One extract model per event type, carrying ONLY that type's data block. The event type
# is known before extraction (Step 1), so an all-types schema is pure overhead — and
# Claude's structured outputs rejected it outright ("compiled grammar is too large").
class _SportsExtract(_BaseExtract):
    sports_schedule: List[ScheduleEntry] = []
    sports_key_players: List[PlayerStat] = []


class _TechExtract(_BaseExtract):
    tech_features: List[FeatureItem] = []
    tech_pricing: List[PricingTier] = []
    tech_availability: str = ""
    tech_comparison: str = ""


class _CulturalExtract(_BaseExtract):
    cultural_performers: List[str] = []
    cultural_schedule: List[CulturalScheduleEntry] = []
    cultural_how_to_watch: str = ""
    cultural_location: str = ""


class _BusinessExtract(_BaseExtract):
    business_companies: List[CompanyRef] = []
    business_key_figures: List[LabelValue] = []
    business_market_reaction: str = ""
    business_what_it_means: str = ""


class _DisasterExtract(_BaseExtract):
    disaster_affected_areas: List[AffectedArea] = []
    disaster_impact_stats: List[LabelValue] = []
    disaster_response_efforts: List[str] = []
    disaster_safety_guidance: str = ""


# political / other have no event-specific block — plain base model.
_EXTRACT_MODEL_BY_TYPE: dict[EventType, type[_BaseExtract]] = {
    EventType.sports: _SportsExtract,
    EventType.tech: _TechExtract,
    EventType.cultural: _CulturalExtract,
    EventType.business: _BusinessExtract,
    EventType.disaster: _DisasterExtract,
    EventType.political: _BaseExtract,
    EventType.other: _BaseExtract,
}


def _flat_to_topic_page(data: "_BaseExtract", event_type: EventType) -> TopicPage:
    sports_data = None
    tech_data = None
    cultural_data = None
    business_data = None
    disaster_data = None

    if event_type == EventType.sports and (data.sports_schedule or data.sports_key_players):
        sports_data = SportsData(
            schedule=data.sports_schedule,
            key_players=data.sports_key_players or None,
        )
    elif event_type == EventType.tech and (data.tech_features or data.tech_availability):
        tech_data = TechData(
            features=data.tech_features,
            pricing=data.tech_pricing or None,
            availability=data.tech_availability or None,
            comparison=data.tech_comparison or None,
        )
    elif event_type == EventType.cultural and (data.cultural_performers or data.cultural_schedule):
        cultural_data = CulturalData(
            performers=data.cultural_performers,
            schedule=data.cultural_schedule,
            how_to_watch=data.cultural_how_to_watch or None,
            location=data.cultural_location or None,
        )
    elif event_type == EventType.business and (data.business_companies or data.business_key_figures):
        business_data = BusinessData(
            companies=data.business_companies,
            key_figures=data.business_key_figures,
            market_reaction=data.business_market_reaction or None,
            what_it_means=data.business_what_it_means or None,
        )
    elif event_type == EventType.disaster and (data.disaster_affected_areas or data.disaster_impact_stats):
        disaster_data = DisasterData(
            affected_areas=data.disaster_affected_areas,
            impact_stats=data.disaster_impact_stats,
            response_efforts=data.disaster_response_efforts,
            safety_guidance=data.disaster_safety_guidance or None,
        )

    return TopicPage(
        title=data.title,
        summary=data.summary,
        event_type=event_type,
        last_updated=data.last_updated,
        key_facts=[KeyFact(label=f.label, value=f.value, source_ids=f.source_ids) for f in data.key_facts],
        timeline=[TimelineEntry(date=t.date, description=t.description, source_ids=t.source_ids) for t in data.timeline],
        entities=data.entities,
        sources=data.sources,
        sports_data=sports_data,
        tech_data=tech_data,
        cultural_data=cultural_data,
        business_data=business_data,
        disaster_data=disaster_data,
    )

EXTRACT_PROMPT = """You are extracting structured data for a news topic page.

Event: "{sentence}"
Event Type: {event_type}
Today's date: {today}

## Search Results
Each result is numbered like [1], [2], ... Use those numbers to cite your sources.

{search_results}

## Task
Extract all available information from the search results above to fill the topic page schema.
Only include information that appears in the search results — do not add facts from your training data.
If a field cannot be filled from the results, use an empty list or null.

## Temporal relevance (important)
This page covers the event as it stands now (today is {today}). key_facts, schedule,
standings, key_players, and other event-specific data blocks must describe the CURRENT
edition of the event and its current participants only — stats and results from this
event or its immediate season.
Historical facts — past winners, past editions, venue history, legacy figures — must NOT
appear in those fields, even if search results mention them prominently. The only exception
is a fact that is itself about the current edition (e.g. "first stadium to host three
opening matches" is fine; "Pelé won here in 1970" is not). Historical material that doesn't
fit this rule should simply be omitted.

## Citations (important)
Every key_fact and every timeline entry MUST carry a `source_ids` array listing the result
numbers ([n]) whose excerpt directly supports that specific claim. Cite every result that
supports the claim, not just one — this lets a later step detect agreement and conflicts.
- Only cite a number if that result's excerpt actually states the claim. Never invent a number.
- If no result supports a claim, do not include the claim at all.
- In `sources`, set each source's `id` to the [n] number it corresponds to in the results above.
  Include a source in the list only if at least one fact or timeline entry cites it.

Rules:
- summary: 2-3 sentences, present tense, factual
- key_facts: 4-6 most important numbers/dates/stats, each with source_ids
- timeline: chronological, most recent first, 4-8 entries, each with source_ids
- entities: include only entities mentioned in the results AND involved in the current event (no historical figures)
- sources: include only URLs from the search results provided, each with its id
- {event_type_instruction}"""

EVENT_TYPE_INSTRUCTIONS = {
    "sports": "Fill sports_data with schedule entries (date, matchup, venue), key players, standings if available. key_players must be players active in this edition of the event, with stats from this event only — never legacy figures from past editions. Leave all other event-specific data blocks null.",
    "tech": "Fill tech_data with features list, pricing if mentioned, availability date. Leave all other event-specific data blocks null.",
    "cultural": "Fill cultural_data with performers list, schedule entries, how_to_watch info if available. Leave all other event-specific data blocks null.",
    "business": "Fill business_data with the companies involved (name, ticker if public, role), key figures (deal size, price moves, valuations), market reaction, and a short what-it-means. Leave all other event-specific data blocks null.",
    "disaster": "Fill disaster_data with affected areas (name + impact), impact stats (magnitude, casualties, damage), response/relief efforts, and official safety guidance if reported. Leave all other event-specific data blocks null.",
    "political": "Leave all event-specific data blocks null. Focus on timeline and entities.",
    "other": "Leave all event-specific data blocks null.",
}

# Drift guard: every EventType must have an extraction instruction. Fails at import,
# not mid-pipeline, when a class is added to the enum but not here.
assert set(EVENT_TYPE_INSTRUCTIONS) == {e.value for e in EventType}, \
    f"EVENT_TYPE_INSTRUCTIONS out of sync with EventType: {set(EVENT_TYPE_INSTRUCTIONS) ^ {e.value for e in EventType}}"

def _format_search_results(results: list[SearchResult]) -> str:
    parts = []
    for i, r in enumerate(results[:20], 1):
        parts.append(
            f"[{i}] {r.title}\n"
            f"    Source: {r.publisher} | {r.url}\n"
            f"    Date: {r.date}\n"
            f"    {r.excerpt}\n"
        )
    return "\n".join(parts)


def _build_prompt(sentence: str, event_type: str, results: list[SearchResult]) -> str:
    return EXTRACT_PROMPT.format(
        sentence=sentence,
        event_type=event_type,
        today=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        search_results=_format_search_results(results),
        event_type_instruction=EVENT_TYPE_INSTRUCTIONS.get(event_type, EVENT_TYPE_INSTRUCTIONS["other"])
    )


def _normalize_sources(page: TopicPage) -> TopicPage:
    """Re-index sources to contiguous 1..N citation numbers and remap fact/timeline
    source_ids onto the new numbering. Deterministic — keeps the LLM's fuzzy [n]
    references honest and gives the rendered page clean, gap-free citations.

    Any source_id that doesn't point at a real extracted source is dropped (the LLM
    occasionally cites a result it never added to `sources`).
    """
    old_to_new: dict[int, int] = {}
    for new_id, src in enumerate(page.sources, start=1):
        if src.id and src.id not in old_to_new:
            old_to_new[src.id] = new_id
        src.id = new_id

    def remap(ids: list[int]) -> list[int]:
        seen: set[int] = set()
        out: list[int] = []
        for i in ids:
            new = old_to_new.get(i)
            if new is not None and new not in seen:
                seen.add(new)
                out.append(new)
        return out

    for f in page.key_facts:
        f.source_ids = remap(f.source_ids)
    for t in page.timeline:
        t.source_ids = remap(t.source_ids)

    return page


async def extract_topic_data(
    sentence: str,
    classification: ClassificationResult,
    results: list,
    provider: str
) -> TopicPage:
    prompt = _build_prompt(sentence, classification.event_type.value, results)

    # Both providers fill the same per-event-type structured-output model
    # (Claude via messages.parse, Gemini via response_schema), then share one converter.
    if provider == "claude":
        page = await _extract_claude(prompt, classification.event_type)
    else:
        page = await _extract_gemini(prompt, classification.event_type)

    return _normalize_sources(page)


async def _extract_claude(prompt: str, event_type: EventType) -> TopicPage:
    client = anthropic_client()
    model_cls = _EXTRACT_MODEL_BY_TYPE[event_type]

    response = await call_with_fallback("claude", lambda model: client.messages.parse(
        model=model,
        max_tokens=16000,
        messages=[{"role": "user", "content": prompt}],
        output_format=model_cls,
    ))

    extracted = response.parsed_output
    if extracted is None:
        # Per docs: refusals and max_tokens truncation bypass the schema guarantee.
        logger.error("Claude returned no parseable extraction (stop_reason=%s)", response.stop_reason)
        raise ValueError("Claude did not return structured extraction output.")
    return _flat_to_topic_page(extracted, event_type)


async def _extract_gemini(prompt: str, event_type: EventType) -> TopicPage:
    client = gemini_client()
    loop = asyncio.get_event_loop()
    model_cls = _EXTRACT_MODEL_BY_TYPE[event_type]

    response = await call_with_fallback("gemini", lambda model: loop.run_in_executor(
        None, lambda: client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=model_cls,
                max_output_tokens=16000
            )
        )
    ))

    extracted = model_cls.model_validate_json(response.text)
    return _flat_to_topic_page(extracted, event_type)
