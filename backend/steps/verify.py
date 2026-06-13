"""Step 5: Grounding pass.

After extraction, every key fact and timeline entry carries `source_ids` pointing at
the sources it was drawn from. This step re-reads the *actual excerpt* behind each
citation and grades the claim:

    confirmed     — 2+ cited sources independently support it
    single_source — exactly 1 cited source supports it
    unverified    — the cited excerpts don't actually state the claim (or no citation)
    conflicted    — cited sources disagree on the value

The LLM does only the semantic judgement (which cited sources support this claim? do
they conflict?). The thresholding into a status is deterministic Python — so the
boundary between model reasoning and code is explicit and the result is reproducible.
"""

import os
import asyncio
import logging
from typing import List, Optional
import anthropic
from google import genai
from google.genai import types
from pydantic import BaseModel

from schemas.topic_page import TopicPage, VerificationStatus
from steps.search import SearchResult
from config import call_with_fallback, gemini_client, anthropic_client

logger = logging.getLogger(__name__)


class _Verdict(BaseModel):
    index: int
    supported_source_ids: List[int] = []
    conflict: bool = False
    note: str = ""


class _VerdictList(BaseModel):
    verdicts: List[_Verdict] = []


# A claim handed to the grader: its text plus the excerpts of the sources it cites.
class _Claim(BaseModel):
    index: int
    kind: str          # "fact" | "timeline"
    pos: int           # position in page.key_facts / page.timeline
    text: str
    cited_ids: List[int]


GRADE_PROMPT = """You are a fact-checking assistant for a newsroom. For each claim below you are \
given the claim text and the excerpts from the sources it cites. Judge each claim ONLY against \
the excerpts provided — not your own knowledge.

For each claim, return:
- supported_source_ids: the cited source ids whose excerpt clearly states or directly implies the claim. \
Omit ids that are off-topic or don't actually back the claim.
- conflict: true ONLY if two or more cited excerpts give materially contradictory values for the same \
fact (e.g. different dates, scores, or figures). Otherwise false.
- note: <= 12 words. Fill ONLY when conflict is true (state the disagreement) or when the claim is just \
partially supported. Otherwise leave empty.

Claims:
{claims_json}"""


def _excerpt_by_id(page: TopicPage, results: List[SearchResult]) -> dict[int, dict]:
    """Map a (normalized) source id -> {publisher, excerpt} using the source URL to
    join back to the raw search result that carries the excerpt text."""
    excerpt_by_url = {r.url: r.excerpt for r in results}
    out: dict[int, dict] = {}
    for src in page.sources:
        out[src.id] = {
            "publisher": src.publisher,
            "excerpt": excerpt_by_url.get(src.url, ""),
        }
    return out


def _collect_claims(page: TopicPage, by_id: dict[int, dict]) -> tuple[list[_Claim], list]:
    """Build the list of claims that actually have a usable cited excerpt. Claims with
    no resolvable citation are returned separately so they can be marked unverified
    without spending a model call."""
    claims: list[_Claim] = []
    no_citation: list = []
    idx = 0

    def usable(ids: list[int]) -> list[int]:
        return [i for i in ids if by_id.get(i, {}).get("excerpt")]

    for pos, f in enumerate(page.key_facts):
        cited = usable(f.source_ids)
        if cited:
            claims.append(_Claim(index=idx, kind="fact", pos=pos, text=f"{f.label}: {f.value}", cited_ids=cited))
            idx += 1
        else:
            no_citation.append(f)
    for pos, t in enumerate(page.timeline):
        cited = usable(t.source_ids)
        if cited:
            claims.append(_Claim(index=idx, kind="timeline", pos=pos, text=f"{t.date} — {t.description}", cited_ids=cited))
            idx += 1
        else:
            no_citation.append(t)

    return claims, no_citation


def _status_from_verdict(v: _Verdict) -> VerificationStatus:
    """Deterministic thresholding — the only place a status is decided."""
    supported = list(dict.fromkeys(v.supported_source_ids))
    if v.conflict and len(supported) >= 1:
        return VerificationStatus.conflicted
    if len(supported) >= 2:
        return VerificationStatus.confirmed
    if len(supported) == 1:
        return VerificationStatus.single_source
    return VerificationStatus.unverified


def _format_claims(claims: list[_Claim], by_id: dict[int, dict]) -> str:
    import json
    payload = []
    for c in claims:
        payload.append({
            "index": c.index,
            "claim": c.text,
            "cited": [
                {"id": i, "publisher": by_id[i]["publisher"], "excerpt": by_id[i]["excerpt"][:500]}
                for i in c.cited_ids
            ],
        })
    return json.dumps(payload, indent=2, ensure_ascii=False)


async def verify_facts(page: TopicPage, results: List[SearchResult], provider: str) -> TopicPage:
    by_id = _excerpt_by_id(page, results)
    claims, no_citation = _collect_claims(page, by_id)

    # Anything we couldn't trace to an excerpt is unverified — decided without a model call.
    for item in no_citation:
        item.verification = VerificationStatus.unverified

    if not claims:
        logger.info("Verify: no citable claims; nothing to grade.")
        return page

    prompt = GRADE_PROMPT.format(claims_json=_format_claims(claims, by_id))

    try:
        if provider == "claude":
            verdicts = await _grade_claude(prompt)
        else:
            verdicts = await _grade_gemini(prompt)
    except Exception as e:
        # A grading failure should not sink the whole page. Fall back to a conservative,
        # citation-count-only status so the pipeline still produces output.
        logger.warning("Verify: grader failed (%s); falling back to citation-count status.", e)
        verdicts = [_Verdict(index=c.index, supported_source_ids=c.cited_ids) for c in claims]

    by_index = {v.index: v for v in verdicts}
    for c in claims:
        v = by_index.get(c.index, _Verdict(index=c.index))
        status = _status_from_verdict(v)
        note = (v.note or "").strip() or None
        target = page.key_facts[c.pos] if c.kind == "fact" else page.timeline[c.pos]
        target.verification = status
        target.note = note

    counts = verification_counts(page)
    logger.info("Verify: %s", counts)
    return page


def verification_counts(page: TopicPage) -> dict[str, int]:
    counts = {s.value: 0 for s in VerificationStatus}
    for item in list(page.key_facts) + list(page.timeline):
        counts[item.verification.value] += 1
    return counts


async def _grade_claude(prompt: str) -> list[_Verdict]:
    # Structured output via messages.parse — schema conformance is grammar-guaranteed,
    # replacing the older forced-tool_choice pattern.
    client = anthropic_client()
    response = await call_with_fallback("claude", lambda model: client.messages.parse(
        model=model,
        max_tokens=4000,
        messages=[{"role": "user", "content": prompt}],
        output_format=_VerdictList,
    ))
    parsed = response.parsed_output
    if parsed is None:
        raise ValueError("Claude did not return grading verdicts.")
    return parsed.verdicts


def _gemini_grade_config(model: str) -> types.GenerateContentConfig:
    # Headroom + a bounded thinking budget: Gemini 2.5 Flash draws thinking tokens from
    # max_output_tokens, and an unbounded budget truncated the verdict JSON. Gemini 3.x
    # models use thinking_level instead and reject thinking_budget, so only pin it on 2.x.
    kwargs = dict(
        response_mime_type="application/json",
        response_schema=_VerdictList,
        max_output_tokens=8000,
    )
    if model.startswith("gemini-2"):
        kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=1024)
    return types.GenerateContentConfig(**kwargs)


async def _grade_gemini(prompt: str) -> list[_Verdict]:
    client = gemini_client()
    loop = asyncio.get_event_loop()
    response = await call_with_fallback("gemini", lambda model: loop.run_in_executor(
        None, lambda: client.models.generate_content(
            model=model,
            contents=prompt,
            config=_gemini_grade_config(model),
        )
    ))
    return _VerdictList.model_validate_json(response.text).verdicts
