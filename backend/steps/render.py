import os
import re
import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
import anthropic
from google import genai
from google.genai import types

from schemas.topic_page import TopicPage
from steps.html_lint import find_issues, repair
from config import call_with_fallback, gemini_client, anthropic_client

logger = logging.getLogger(__name__)

AESTHETICS_PROMPT = """
<frontend_aesthetics>
You tend to converge toward generic, "on distribution" outputs. In frontend design, this creates what users call the "AI slop" aesthetic. Avoid this: make creative, distinctive frontends that surprise and delight.

Before designing, commit to a BOLD aesthetic direction:
- Tone: pick a clear flavor and name it to yourself — brutally minimal, maximalist, retro-futuristic, editorial/magazine, brutalist/raw, art deco/geometric, luxury/refined, industrial/utilitarian, organic/natural — whatever is truest to THIS event. Bold maximalism and refined minimalism both work; the key is intentionality, not intensity.
- Differentiation: decide what the ONE thing someone will remember about this page is, and execute it with precision.

Focus on:

Typography: Choose fonts that are beautiful, unique, and interesting. Avoid generic fonts like Arial and Inter; opt instead for distinctive choices that elevate the frontend's aesthetics. Pair a characterful display font with a refined body font. Use Google Fonts @import.

Color & Theme: Commit to a cohesive aesthetic. Use CSS variables for consistency. Dominant colors with sharp accents outperform timid, evenly-distributed palettes. Draw from IDE themes and cultural aesthetics for inspiration. Vary between light and dark themes — dark themes are often more striking.

Spatial Composition: Avoid the predictable centered-column-of-cards layout. Consider asymmetry, overlap, diagonal flow, a grid-breaking hero element, generous negative space OR controlled editorial density — whichever serves the chosen tone.

Motion: Use CSS animations for page load. One well-orchestrated stagger effect creates delight. IMPORTANT: implement stagger with CSS custom properties and calc() — NEVER write individual nth-child animation-delay rules for more than 4-5 elements. Keep the total CSS under 200 lines.

Backgrounds: Create atmosphere and depth rather than defaulting to solid colors. Layer CSS gradients, use geometric patterns, noise/grain textures, layered transparencies, or dramatic shadows that match the overall aesthetic.

Avoid generic AI-generated aesthetics:
- Overused font families (Inter, Roboto, Arial, system fonts, Space Grotesk)
- Clichéd color schemes (particularly purple gradients on white backgrounds)
- Predictable layouts and component patterns
- Cookie-cutter design that lacks context-specific character

No two pages should look the same. NEVER converge on the same fonts, palette, or layout across generations.
</frontend_aesthetics>
"""

RENDER_PROMPT = """You are the art director and frontend designer for a one-off editorial topic page. You have full creative authority over the design. You have ZERO authority over the content contract at the end — every item in it must be present and correct.

Event Type: {event_type}
Event Title: {title}
Today's date: {today}

Event Data (JSON):
{data_json}

{aesthetics}

## Find the design inside the data — not inside the category
Do not design "a {event_type} page". Design THIS event's page. The JSON above is your creative brief:
- The venues, cities, people, brands, dates and stakes in the data carry a visual identity — a host city's culture and color, a brand's actual design language, a tournament's graphic heritage, a genre's poster tradition, an era's typography.
- Pick 2-3 concrete specifics from the data and let THEM dictate palette, type, texture and layout. Two events of the same type must NOT look like siblings.

## Choose a direction (silently, before writing any code)
1. Sketch three CONTRASTING art directions for this event — vary tone, light vs dark, type era, layout philosophy.
2. Discard whichever one a generic AI would reach for first. Forbidden defaults: "dark stadium with neon glow" for sports, "dark mode with electric blue/cyan" for tech, "warm gradient concert poster" for cultural, "red urgent banner" for political, "navy dashboard with green/red arrows" for business, "alarm-red emergency screen" for disaster.
   ALSO forbidden — your second-order default: the "archival print" family (letterpress / broadside / aged paper / ink-on-cream-or-bone / vintage document conceit with serif display + typewriter mono). You reach for it for EVERY type once the first defaults are banned. Use it only if the event is itself historical; otherwise pick a direction that is unmistakably contemporary — and commit to a real position on the light↔dark and saturated↔muted axes rather than defaulting to muted paper neutrals.
3. Commit to the strongest remaining direction. Write its name as an HTML comment on line 2 of the document, e.g. <!-- direction: Azteca matchday programme, art-deco geometry, ink on cream -->. Every choice after that must serve the named direction.

## Imagine the lineup
This page will sit in a portfolio next to pages for other events. They must look like they came from different design studios. If your design would also work for a different event of the same type with the words swapped, it is wrong — start over at step 1.

═══════════════ CONTENT CONTRACT (non-negotiable) ═══════════════

## Status banner (compute from "Today's date" above — this is a static page, no JS)
Near the hero, render a status indicator derived from the event's dates vs. today:
- Main event date in the future → "UPCOMING · in N days" (compute N and bake it in).
- Today inside the event window → "HAPPENING NOW".
- Event passed → "CONCLUDED".
Its visual form is yours (pill, stamp, ticker, marginal note) — its logic is not. No JavaScript, no live countdown.

## Event-specific data (all of it must be rendered, visibly and comparably)
- sports_data: every schedule entry (date · matchup · venue · result) in a structure a reader can scan and compare — classic table, fixture board, ticket-stub list: your call. Standings and key players too, if present.
- tech_data: every feature, the full pricing comparison (tier × price) if present, and the availability/comparison callout.
- cultural_data: all performers, the full running-order schedule, and the how-to-watch information.
- business_data: the companies involved (with tickers and roles), every key figure (deal sizes, price moves), the market reaction, and the what-it-means callout. Numbers must dominate.
- disaster_data: every affected area with its impact, all impact stats (magnitude, casualties, damage), response/relief efforts, and — most prominently — the safety guidance. Urgency-first, information before decoration.
- political/other: lead with the timeline and an impact-style summary.
The FORM is free; omitting or truncating the data is a contract violation.

## Required content (render all non-empty sections; hide empty ones gracefully)
- Hero: event title (prominent), type badge, last updated, summary paragraph
- Status banner (above)
- Key facts: all of them, scannable — the form (cards, ticker, oversized numerals, ledger rows…) is yours
- Event-specific section (above)
- Timeline: chronological — spine, horizontal strip, calendar, numbered acts: your call
- Key entities: people, orgs, locations with roles
- Related Coverage: source list with publisher, title, date, link

## Technical requirements
- Single self-contained HTML file
- All CSS inside one <style> tag — no external CSS files, no inline style attributes
- Google Fonts via @import only (no other CDN)
- No JavaScript
- Responsive (works at 375px and 1200px+)
- CSS MUST be concise: use classes and descendant selectors, NOT individual nth-child rules for every list item. Stagger animations with a CSS variable + calc() pattern on the parent, not per-element rules.

Return ONLY the complete HTML document. No markdown fences, no explanation."""


def _strip_provenance(data: dict) -> dict:
    """Remove provenance/verification fields before rendering. They stay in the Step 5
    checkpoint and the Review panel (the editorial surface); the published page itself
    presents the post-review content without trust markup."""
    for item in data.get("key_facts", []) + data.get("timeline", []):
        for field in ("source_ids", "verification", "note"):
            item.pop(field, None)
    for src in data.get("sources", []):
        src.pop("id", None)
    return data


# LLM renders occasionally ship self-breaking CSS (e.g. animation pointing at undefined
# @keyframes -> content stuck at opacity 0). Each render is linted; on failure we re-roll
# the LLM, and if every attempt fails we deterministically repair the last one — a broken
# page can never ship.
MAX_RENDER_ATTEMPTS = 3


async def render_page(page: TopicPage, provider: str = "claude") -> str:
    data = _strip_provenance(page.model_dump(exclude_none=True))
    prompt = RENDER_PROMPT.format(
        event_type=page.event_type.value,
        title=page.title,
        today=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        data_json=json.dumps(data, indent=2, ensure_ascii=False),
        aesthetics=AESTHETICS_PROMPT,
    )

    logger.info("Rendering HTML via %s for event: %s", provider, page.title)

    html = ""
    for attempt in range(1, MAX_RENDER_ATTEMPTS + 1):
        if provider == "claude":
            html = await _render_claude(prompt)
        else:
            html = await _render_gemini(prompt)
        html = _clean_html(html)

        issues = find_issues(html)
        if not issues:
            if attempt > 1:
                logger.info("Render passed lint on attempt %d/%d", attempt, MAX_RENDER_ATTEMPTS)
            return html
        logger.warning(
            "Render attempt %d/%d failed lint: %s",
            attempt, MAX_RENDER_ATTEMPTS, "; ".join(issues),
        )

    html, fixes = repair(html)
    logger.warning(
        "Render lint failing after %d attempts; applied deterministic repair: %s",
        MAX_RENDER_ATTEMPTS, "; ".join(fixes) or "none needed",
    )
    return html


async def _render_claude(prompt: str) -> str:
    client = anthropic_client()

    # 16384 keeps the SDK's projected duration under its 10-minute non-streaming guard
    # and is ample for the largest pages seen so far (~42KB ≈ 12k tokens).
    response = await call_with_fallback("claude", lambda model: client.messages.create(
        model=model,
        max_tokens=16384,
        messages=[{"role": "user", "content": prompt}]
    ))

    text = response.content[0].text
    logger.info(
        "Claude render: stop_reason=%s input_tokens=%d output_tokens=%d output_chars=%d",
        response.stop_reason,
        response.usage.input_tokens,
        response.usage.output_tokens,
        len(text),
    )
    if response.stop_reason == "max_tokens":
        logger.warning("Claude render hit max_tokens — HTML is truncated. Raise max_tokens in render.py.")

    return text


def _gemini_render_config(model: str) -> types.GenerateContentConfig:
    # Gemini 2.5 Flash spends "thinking" tokens out of max_output_tokens. For a pure
    # HTML-generation task that left too little budget for the document itself and
    # truncated the page mid-render. Disable thinking so the full budget goes to output.
    # Gemini 3.x models use thinking_level instead and reject thinking_budget, so only
    # pin it on 2.x.
    kwargs = dict(max_output_tokens=32000)
    if model.startswith("gemini-2"):
        kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=0)
    return types.GenerateContentConfig(**kwargs)


async def _render_gemini(prompt: str) -> str:
    client = gemini_client()
    loop = asyncio.get_event_loop()

    response = await call_with_fallback("gemini", lambda model: loop.run_in_executor(
        None, lambda: client.models.generate_content(
            model=model,
            contents=prompt,
            config=_gemini_render_config(model),
        )
    ))

    text = response.text
    candidate = response.candidates[0] if response.candidates else None
    finish_reason = candidate.finish_reason.name if candidate and candidate.finish_reason else "unknown"
    usage = response.usage_metadata
    logger.info(
        "Gemini render: finish_reason=%s input_tokens=%s output_tokens=%s output_chars=%d",
        finish_reason,
        usage.prompt_token_count if usage else "?",
        usage.candidates_token_count if usage else "?",
        len(text),
    )
    if finish_reason == "MAX_TOKENS":
        logger.warning("Gemini render hit MAX_TOKENS — HTML is truncated. Raise max_output_tokens in render.py.")

    return text


def _clean_html(text: str) -> str:
    text = text.strip()
    # Strip markdown code fences if LLM wrapped the output
    text = re.sub(r'^```[a-z]*\n?', '', text)
    text = re.sub(r'\n?```\s*$', '', text)
    return text.strip()


def save_page(page: TopicPage, html: str, run_dir: Path) -> Path:
    slug = page.title.lower().replace(" ", "-")[:60]
    slug = "".join(c for c in slug if c.isalnum() or c == "-") or "output"
    filepath = run_dir / f"{slug}.html"

    # Regenerations never overwrite: the first render keeps the plain name (implicitly v1),
    # re-renders of the same run save alongside it as {slug}-v2.html, -v3.html, ...
    if filepath.exists():
        i = 2
        while (run_dir / f"{slug}-v{i}.html").exists():
            i += 1
        filepath = run_dir / f"{slug}-v{i}.html"

    filepath.write_text(html, encoding="utf-8")
    return filepath
