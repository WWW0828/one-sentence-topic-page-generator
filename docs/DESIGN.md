# One-Sentence Topic Page Generator

This document explains *why* the system is built the way it is. It covers the product decisions behind it, the architecture, the data contract, how it sources real information, the failure modes it defends against, and what I'd do with another week.

---

## 1. Product decisions

### Who this is for

I designed this as an **internal editorial tool**, not a consumer "type a sentence, get a magic page" toy. The user is someone on a content or newsroom team who needs to stand up a credible topic page **fast** when an event breaks, and who is accountable for what gets published. That single framing drives most of the product decisions below.

A consumer tool optimizes for "one click, walk away." An internal tool optimizes for **speed with a human in control**. The operator should be able to watch the work happen, inspect what the model extracted, throw out anything that looks shaky, and re-render, all in well under a minute of hands-on time. Three features fall directly out of that.

1. **Per-step pre-generation with checkpoint and resume.** The pipeline runs as six discrete, individually-checkpointed steps (`output/{run}/checkpoints/step_N.json`). The UI streams each step's result as it lands, and any step can be re-run *from that point forward* (`from_step`) without paying for the steps before it. If search surfaced junk, the operator re-runs from search. If extraction missed a fact, re-run from extraction, and the classification and the expensive search results are reused from their checkpoints. This makes the tool cheap to iterate with, and it makes a slow or failed run recoverable instead of a full restart.

2. **A review and edit panel between data and page.** After verification (Step 5) the UI exposes the **structured data**, not the HTML, as an editable surface. The operator can fix a mangled title, correct a date, reword a fact, change the event type, or **reject** any fact, timeline entry, or entity outright. Editing the *data* (never the rendered markup) keeps the structured model the single source of truth, so a re-render is deterministic and provenance survives the round-trip. The pre-edit verifier output is backed up (`step_5.original.json`) so an operator can always revert to "what the machine said" after hand-editing.

3. **Source-verification tags the operator can act on.** Every key fact and timeline entry is graded against its own cited sources (`confirmed`, `single_source`, `unverified`, `conflicted`) and that tag is shown inline in the review panel, next to the actual sources behind the claim. The point isn't to hide weak facts. It's to *flag* them so a human decides. An operator can reject a `single_source` or `unverified` claim before it ever reaches the published HTML. The published page itself drops the trust markup (it's an editorial signal, not reader-facing), but the decision of what survives is the operator's.

The throughline: the LLM does the grunt work of research and drafting, and the human keeps editorial authority and a fast feedback loop.

### What belongs on a topic page

A topic page is not an article. It's a **structured surface that aggregates context**. I settled on a fixed spine that every event gets:

- **Hero**: title, event-type badge, last-updated, a two-to-three-sentence summary.
- **Status banner**: `UPCOMING · in N days` / `HAPPENING NOW` / `CONCLUDED`, computed from the event dates against today. This is the single most "topic-page-ish" element. It tells a reader at a glance whether this is breaking, live, or retrospective.
- **Key facts**: the four to six numbers, dates, and stats that define the event.
- **Timeline**: chronological key developments.
- **Key entities**: the people, orgs, and locations involved, with roles.
- **Related coverage**: the cited sources.

### How the shape adapts to event type

The fixed spine is deliberately *not* the whole page. The hard part of this brief is making a sports page not look like a tech page with the words swapped, and I attack that on two axes.

**Data axis: typed, event-specific blocks.** Five of the seven event types carry a bespoke data block that the spine can't express:

| Type | Extra block | Why it needs one |
|---|---|---|
| `sports` | schedule (date·matchup·venue·result), key players | a fixture list and a flat fact-grid are different shapes |
| `tech` | features, pricing tiers, availability, comparison | a product launch lives or dies on its feature/pricing table |
| `cultural` | performers, running order, how-to-watch | a festival is a lineup plus a schedule |
| `business` | companies (ticker/role), key figures, market reaction | a deal is fundamentally about numbers and parties |
| `disaster` | affected areas, impact stats, response efforts, **safety guidance** | safety info has to be first-class and prominent |

`political` and `other` deliberately get **no** block. Forcing structured data onto "the G7 summit" or "a solar eclipse" would invent rigidity that doesn't fit, so they lead with timeline plus entities instead. The decision rule was: *add a typed block only where a whole category of events genuinely shares a strong sub-structure; otherwise don't.* This is the answer to "a schema that survives three different event types without becoming a `Map<string, any>`": typed where structure is real, absent where it isn't.

**Visual axis: the render is told to design *this event*, not *this category*.** The render prompt forbids the obvious per-type defaults ("dark stadium with neon glow" for sports, "navy dashboard with red/green arrows" for business, and so on). It also forbids the second-order default an LLM reaches for once those are banned, the "aged-paper / letterpress / archival" look. It must pull two or three concrete specifics from the actual data (host city, brand, venue, era) and let those drive palette, type, and layout, then commit to a named art direction recorded as an HTML comment on line 2. Two events of the *same* type should look like they came from different design studios.

### What I intentionally left out

- **Hosting, deploy, auth, accounts, persistence.** Out of scope per the brief; the deliverable is openable HTML files. Runs persist to the local filesystem, which is all an internal tool needs.
- **Live auto-updating pages.** The status banner is computed at render time with no JS, so the page is a self-contained snapshot. A truly live page is a different product (a feed, not a document).
- **Multi-article aggregation, comment threads, related-topics graph.** A real topic page surface eventually wants these. They're noted in §6, not built.

---

## 2. System architecture

### The pipeline

```
sentence
   │
   ▼
[1] Classify ──(gate: refuse / ambiguous)──▶ stop, surface to user
   │  event_type, title, entities, confidence, verdict
   ▼
[2] Query-gen ───▶ 6–8 targeted search queries
   ▼
[3] Search (Tavily) ───▶ deduped sources with excerpts
   ▼
[4] Extract ───▶ TopicPage (facts/timeline/entities + typed block), each claim cited
   ▼
[5] Verify (grounding) ───▶ same TopicPage, each claim graded vs. its cited excerpts
   │                          └─ editable in the Review panel ──┐
   ▼                                                            │ (re-render from step 6)
[6] Render ──▶ HTML ──▶ deterministic lint ──(fail)──▶ re-roll ×3 ──▶ deterministic repair
   │
   ▼
self-contained .html
```

Each step is a separate module under `steps/`, checkpointed independently, and streamed to the client over Server-Sent Events with status and elapsed time.

### The LLM/deterministic-code boundary

This is the part I care most about. The rule is: **the LLM does open-ended semantic judgment; deterministic Python does anything with a right answer.** Concretely:

| Concern | LLM does | Code does |
|---|---|---|
| Verification | "which cited excerpts actually support this claim? do they conflict?" | thresholds the answer into `confirmed`/`single_source`/`unverified`/`conflicted` (`_status_from_verdict`) |
| Citations | emits `[n]` references while extracting | re-indexes sources to contiguous `1..N`, remaps fact→source ids, **drops dangling citations** (`_normalize_sources`) |
| HTML safety | writes the page | lints for broken `@keyframes`/truncation and repairs deterministically (`html_lint.py`), never a model call |
| Status banner | nothing | "UPCOMING in N days / NOW / CONCLUDED" is computed from dates, not asked of the model |

Keeping the *thresholding* out of the model is what makes verification reproducible: the same verdict always maps to the same label. Keeping citation re-indexing in code is what makes the rendered footnotes gap-free and honest even when the model cites loosely.

### Why this shape is debuggable and observable

- **Checkpoints** mean any run can be inspected step-by-step on disk and resumed from any point. That's essential for an internal tool and for development (the test harness reuses the same checkpoint plumbing).
- **SSE streaming** surfaces per-step status and latency live, so a slow or failing step is visible immediately rather than as one opaque spinner.
- **`from_step` resume** turns "regenerate" from a full re-run into a targeted re-run.

### Stack choices (and why they're defensible)

- **FastAPI plus SSE.** The pipeline is naturally a stream of step events, and SSE is the simplest correct transport for "push me each step as it finishes" without WebSocket overhead. FastAPI's async model fits the IO-bound LLM and search calls.
- **React, Vite, Tailwind.** The value of this tool is the *review/edit* surface, which is genuinely interactive (per-row reject toggles, dirty-tracking, live re-render). That's a real frontend, so a real frontend framework is warranted.
- **Pydantic.** One schema definition drives both providers' structured output *and* runtime validation of checkpoints, so the data contract has a single source of truth.
- **Two LLM providers (Claude and Gemini), selectable at runtime.** 

---

## 3. Prompt and data contract

### The schema (`schemas/topic_page.py`)

The core `TopicPage`:

```python
class TopicPage(BaseModel):
    title: str
    summary: str
    event_type: EventType            # sports|tech|business|disaster|cultural|political|other
    last_updated: str
    key_facts: list[KeyFact]         # label, value, source_ids, verification, note
    timeline: list[TimelineEntry]    # date, description, source_ids, verification, note
    entities: list[Entity]           # name, role, type(person|org|location)
    sources: list[Source]            # id, title, url, publisher, date
    sports_data:   Optional[SportsData]   = None
    tech_data:     Optional[TechData]     = None
    cultural_data: Optional[CulturalData] = None
    business_data: Optional[BusinessData] = None
    disaster_data: Optional[DisasterData] = None
```

The design tension the brief calls out, *"too rigid" vs. `Map<string, any>` escape hatch*, is resolved by **shared core fields plus optional typed per-type blocks**. Every event fills the core; only the matching block is populated. There is no untyped bag anywhere, so adding a new event sub-structure means adding a typed model, not stuffing a dict.

Per-claim provenance (`source_ids`, `verification`, `note`) lives **only** on `KeyFact` and `TimelineEntry`, not on the nested block fields. That's a deliberate call: provenance and grading apply to the headline claims, while the typed blocks are render-supporting detail.

### Keeping LLM output conformant

Both providers are forced to emit the schema via **grammar-constrained structured output**, not "please return JSON":

- **Claude**: `messages.parse(output_format=Model)`, where grammar-constrained sampling guarantees schema conformance. We check `parsed_output is None` to catch the documented escape hatches (refusal, `max_tokens` truncation) and raise rather than ship garbage.
- **Gemini**: `response_schema=Model` plus `response_mime_type="application/json"`, then `Model.model_validate_json`.

A guard (`assert set(EVENT_TYPE_INSTRUCTIONS) == {e.value for e in EventType}`) fails at **import time** if someone adds an event type without giving it an extraction instruction, so drift is caught before it can happen mid-pipeline.

---

## 4. Information sourcing

### How real information is pulled

- **Provider: Tavily** (search API), not scraping or a full agent tool-use loop. For this task, "fetch fresh, citeable facts about a named event," a search API returns ranked results with clean excerpts and dates in one call, which is exactly what extraction needs. Scraping adds brittleness (markup, paywalls, JS) for no benefit when the excerpt already carries the claim, and a multi-turn agent loop adds latency and cost I couldn't justify for a single-event lookup.
- **Query generation is its own step.** The LLM turns the one sentence plus classification into 6 to 8 *different-angle* queries (current status, timeline, entities, hard numbers, background). Searching 6 to 8 facets beats one fat query for recall.
- Queries fan out **concurrently**, results are **deduped by URL**, and each result keeps title, resolved publisher (domain), date, and a 600-char excerpt.

### Citations

- The extract prompt requires **every** key fact and timeline entry to carry a `source_ids` array, and to cite **every** supporting result (not just one). That's what later lets the grounder detect agreement versus conflict.
- "Only cite a result whose excerpt actually states the claim; never invent a number; if nothing supports a claim, drop the claim."
- Citations are then **deterministically normalized** (contiguous numbering, dangling ids dropped) so the rendered footnotes are clean and trustworthy regardless of how loosely the model referenced sources.

### Freshness

- **Today's date is injected into every prompt.** The classifier is explicitly told its training data predates today, that it *cannot* verify recency from memory, and that it must not refuse an event just because it's after the knowledge cutoff. Verification happens against live sources downstream.
- Extraction enforces a **temporal-relevance rule**: the page describes the *current edition* of the event only. Historical material (past winners, venue history, legacy figures) is excluded even when sources mention it prominently, which is a common and visible failure mode for recurring events (World Cup, Eurovision, Wimbledon).

### Conflicting sources

This is handled as a first-class verdict. When two cited excerpts give materially contradictory values for the same fact, the grounder flags `conflict`, and the deterministic thresholder labels it `conflicted` with a short note, surfaced to the operator rather than silently picking one.

### Cost and latency

- Single search round, `search_depth="basic"`, 5 results per query, which is enough signal without a deep crawl.
- The pipeline is sequential by design (each step consumes the prior), but each LLM call has a **hard timeout** (300s) so one wedged request can't hang the run indefinitely. This was a real observed failure: a single extraction call stuck for 50+ minutes.
- Checkpoints and `from_step` mean iteration cost is paid once, not per retry.

---

## 5. Failure modes

### LLM hallucination

- **Grounding pass (Step 5)** re-reads the *actual excerpt* behind every citation and grades the claim against the excerpts *only* ("not your own knowledge"). Claims whose citations don't resolve to a usable excerpt are marked `unverified` **without** a model call.
- Extraction is constrained to "only information that appears in the search results; do not add facts from training data."
- If the grader call itself fails, the verifier **degrades gracefully** to a citation-count-only status rather than sinking the whole page.
- The verification tag is exposed to the operator, who can reject anything weak before publish. The last line of defense is a human, by design.

### Ambiguous, off-topic, or adversarial input

The **input gate** (Step 1) classifies the sentence into a verdict *before any search budget is spent*:

- `refuse`: not a buildable news event. Off-topic or nonsensical, physically impossible (aliens, magic), or a **prompt-injection attempt** ("ignore your instructions and …"). The user gets a one-line explanation.
- `ambiguous`: could mean two distinct events, or lacks who/what/when. The user gets two or three concrete, resubmittable interpretations instead of a guess.
- `ok`: proceed. A coherent *series* (a tournament, a festival week, a multi-day summit) is explicitly **not** ambiguous, since it's one name, one page.

A low-confidence (`< 0.4`) but `ok` classification emits a non-blocking warning nudging the operator to add detail. The gate stopping early matters for an internal tool: bad input fails fast and cheap, not after a full research run.

### Broken LLM-generated HTML

The renderer is an LLM, and its most damaging real-world failure was CSS that hides content forever (`opacity: 0` waiting on an `animation` whose `@keyframes` was never emitted, so the page ships invisible). Defense is a **deterministic lint, re-roll, repair** chain (`html_lint.py`):

1. Lint every render for missing-keyframes and truncation.
2. On failure, re-roll the LLM up to 3 times.
3. If all attempts still fail, **deterministically repair** (inject fade-to-visible keyframes, close a truncated document).

A broken page can never ship.

### Provider and capacity failures

`call_with_fallback` runs every LLM call against an ordered model chain per provider, advancing on capacity errors (429/5xx/overloaded/timeout) and wrapping once past the end of the chain. Non-capacity errors (bad request, auth, schema) propagate immediately instead of burning the whole chain. Both providers have explicit request timeouts.

### Known limitations (acknowledged, not defended)

- Verification trusts the **Tavily excerpt**, not the full article, so a claim supported by text outside the excerpt reads as `unverified`.
- No source-**credibility** weighting, so two low-quality sources agreeing counts as `confirmed`.
- Single search pass, with no iterative "I'm missing X, search again" loop.
- No cross-fact dedup, so the same fact phrased two ways can appear twice.
- Changing event type in the review panel re-frames the layout but does **not** re-extract the typed block (the UI warns about this explicitly).

---

## 6. What I'd do with another week

Prioritized:

1. **Full-page fetch for verification.** Pull the cited article body (not just the excerpt) so grounding stops false-flagging well-supported claims as `unverified`. Highest-leverage fix for output trustworthiness.
2. **Source-credibility signal.** Weight publishers (wire services vs. random blog) so `confirmed` means "two *credible* sources," and surface that weighting in the tag.
3. **Iterative search loop.** Let extraction declare "missing: pricing / casualty count" and trigger a second targeted search round before giving up on a field.
4. **Per-type re-extraction on type change** in the review panel, so an operator correcting a misclassification gets the right typed block rather than a stale one.
5. **A real eval score.** Add automated scoring (classification accuracy, % facts confirmed, block-completeness, render-lint pass rate) to catch regressions instead of eyeballing.
6. **Reader-facing polish.** An accessibility audit, a print stylesheet, and optional inline citation markers on the published page.

---

## Appendix: The editorial review/edit loop (data flow)

```
Step 5 verified TopicPage ──▶ Review panel (editable structured data)
                                  │  reject rows / fix wording / change type
                                  ▼
   POST /run/{id}/page  ──▶ saved as step_5 checkpoint
   (first edit backs up the verifier's output to step_5.original.json)
                                  │
                                  ▼
   generate(from_step=6) ──▶ re-render HTML from edited data ──▶ download
```

Edits are always on the structured model, never the HTML, so the data stays the source of truth, a re-render is deterministic, and the operator can always revert to the verifier's original output.
