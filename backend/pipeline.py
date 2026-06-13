import time
import json
import uuid
import logging
from pathlib import Path
from typing import AsyncGenerator, Optional

from steps.classify import classify_event
from steps.query_gen import generate_search_queries
from steps.search import search_web, SearchResult
from steps.extract import extract_topic_data
from steps.verify import verify_facts, verification_counts
from steps.render import render_page, save_page
from schemas.topic_page import TopicPage, ClassificationResult, EventType, Entity, InputVerdict
import checkpoints as ckpt

logger = logging.getLogger(__name__)


def _sse(data: dict) -> str:
    return f"data: {json.dumps(data)}\n\n"


def _ms(t0: float) -> int:
    return int((time.monotonic() - t0) * 1000)


def _classification_from_ckpt(d: dict) -> ClassificationResult:
    return ClassificationResult(
        verdict=InputVerdict(d.get("verdict", "ok")),
        reason=d.get("reason", ""),
        interpretations=d.get("interpretations", []),
        event_type=EventType(d["event_type"]),
        suggested_title=d["suggested_title"],
        entities=[Entity(**e) for e in d.get("entities", [])],
        confidence=d["confidence"]
    )


async def run_pipeline(
    sentence: str,
    provider: str,
    search_source: str,
    run_id: Optional[str] = None,
    from_step: int = 1,
) -> AsyncGenerator[str, None]:

    if not run_id:
        # {llm}-{uuid[:8]} — the provider prefix makes run dirs self-describing
        # (output/0612-0443/gemini-954935b8/) and 8 hex chars is plenty of entropy
        # for a local tool.
        run_id = f"{provider}-{uuid.uuid4().hex[:8]}"

    # Resolve or create the run directory: output/{MMDD-HHMM}/{run_id}/
    run_dir: Path = ckpt.get_or_create_run_dir(run_id)

    yield _sse({"type": "init", "run_id": run_id})

    classification: Optional[ClassificationResult] = None
    queries: Optional[list] = None
    search_results: Optional[list] = None
    topic_page: Optional[TopicPage] = None

    # ── Step 1: Classify ──
    if from_step > 1:
        cp = ckpt.load(run_dir, 1)
        if cp:
            classification = _classification_from_ckpt(cp)
            yield _sse({
                "step": 1, "status": "done", "elapsed_ms": 0, "from_checkpoint": True,
                "result": {
                    "event_type": cp["event_type"],
                    "suggested_title": cp["suggested_title"],
                    "entities": [e["name"] for e in cp.get("entities", [])],
                    "confidence": cp["confidence"],
                }
            })
        else:
            logger.warning("Step 1 checkpoint missing for run %s, re-running from step 1", run_id)
            from_step = 1

    if from_step <= 1:
        yield _sse({"step": 1, "status": "running", "elapsed_ms": 0})
        t0 = time.monotonic()
        try:
            classification = await classify_event(sentence, provider)
        except Exception as e:
            yield _sse({"step": 1, "status": "error", "elapsed_ms": _ms(t0), "error": str(e)})
            return

        ckpt.save(run_dir, 1, {
            "verdict": classification.verdict.value,
            "reason": classification.reason,
            "interpretations": classification.interpretations,
            "event_type": classification.event_type.value,
            "suggested_title": classification.suggested_title,
            "entities": [e.model_dump() for e in classification.entities],
            "confidence": classification.confidence,
        })
        yield _sse({
            "step": 1, "status": "done", "elapsed_ms": _ms(t0),
            "result": {
                "verdict": classification.verdict.value,
                "reason": classification.reason,
                "interpretations": classification.interpretations,
                "event_type": classification.event_type.value,
                "suggested_title": classification.suggested_title,
                "entities": [e.name for e in classification.entities],
                "confidence": classification.confidence,
            }
        })
        if classification.verdict == InputVerdict.ok and classification.confidence < 0.4:
            yield _sse({
                "step": 1, "status": "warning", "elapsed_ms": 0,
                "message": f"Low confidence ({classification.confidence:.0%}). Consider adding more specific details."
            })

    # ── Input gate: stop before spending search budget on bad input ──
    if classification and classification.verdict != InputVerdict.ok:
        logger.info("Input gate blocked run %s: verdict=%s", run_id, classification.verdict.value)
        yield _sse({
            "type": "blocked",
            "verdict": classification.verdict.value,
            "reason": classification.reason,
            "interpretations": classification.interpretations,
        })
        return

    # ── Step 2: Query generation ──
    if from_step > 2:
        cp = ckpt.load(run_dir, 2)
        if cp:
            queries = cp["queries"]
            yield _sse({"step": 2, "status": "done", "elapsed_ms": 0, "from_checkpoint": True, "result": cp})
        else:
            logger.warning("Step 2 checkpoint missing for run %s, re-running from step 2", run_id)
            from_step = 2

    if from_step <= 2:
        yield _sse({"step": 2, "status": "running", "elapsed_ms": 0})
        t0 = time.monotonic()
        try:
            queries = await generate_search_queries(sentence, classification, provider)
        except Exception as e:
            yield _sse({"step": 2, "status": "error", "elapsed_ms": _ms(t0), "error": str(e)})
            return

        ckpt.save(run_dir, 2, {"queries": queries})
        yield _sse({"step": 2, "status": "done", "elapsed_ms": _ms(t0), "result": {"queries": queries}})

    # ── Step 3: Web search ──
    if from_step > 3:
        cp = ckpt.load(run_dir, 3)
        if cp:
            search_results = [SearchResult(**r) for r in cp["results"]]
            yield _sse({
                "step": 3, "status": "done", "elapsed_ms": 0, "from_checkpoint": True,
                "result": {
                    "source_count": len(search_results),
                    "sources": [{"title": r.title, "publisher": r.publisher, "url": r.url} for r in search_results[:8]],
                }
            })
        else:
            logger.warning("Step 3 checkpoint missing for run %s, re-running from step 3", run_id)
            from_step = 3

    if from_step <= 3:
        yield _sse({"step": 3, "status": "running", "elapsed_ms": 0})
        t0 = time.monotonic()
        try:
            search_results = await search_web(queries, search_source)
        except Exception as e:
            yield _sse({"step": 3, "status": "error", "elapsed_ms": _ms(t0), "error": str(e)})
            return

        ckpt.save(run_dir, 3, {"results": [r.model_dump() for r in search_results]})
        yield _sse({
            "step": 3, "status": "done", "elapsed_ms": _ms(t0),
            "result": {
                "source_count": len(search_results),
                "sources": [{"title": r.title, "publisher": r.publisher, "url": r.url} for r in search_results[:8]],
            }
        })

    # ── Step 4: Data extraction ──
    if from_step > 4:
        cp = ckpt.load(run_dir, 4)
        if cp:
            try:
                topic_page = TopicPage.model_validate(cp)
                yield _sse({
                    "step": 4, "status": "done", "elapsed_ms": 0, "from_checkpoint": True,
                    "result": {
                        "title": topic_page.title,
                        "key_facts_count": len(topic_page.key_facts),
                        "timeline_count": len(topic_page.timeline),
                        "entities_count": len(topic_page.entities),
                        "sources_count": len(topic_page.sources),
                        "has_event_specific": any([topic_page.sports_data, topic_page.tech_data, topic_page.cultural_data, topic_page.business_data, topic_page.disaster_data]),
                    }
                })
            except Exception as e:
                logger.warning("Step 4 checkpoint invalid for run %s: %s, re-running", run_id, e)
                from_step = 4
        else:
            logger.warning("Step 4 checkpoint missing for run %s, re-running from step 4", run_id)
            from_step = 4

    if from_step <= 4:
        yield _sse({"step": 4, "status": "running", "elapsed_ms": 0})
        t0 = time.monotonic()
        try:
            topic_page = await extract_topic_data(sentence, classification, search_results, provider)
        except Exception as e:
            yield _sse({"step": 4, "status": "error", "elapsed_ms": _ms(t0), "error": str(e)})
            return

        ckpt.save(run_dir, 4, topic_page.model_dump())
        yield _sse({
            "step": 4, "status": "done", "elapsed_ms": _ms(t0),
            "result": {
                "title": topic_page.title,
                "key_facts_count": len(topic_page.key_facts),
                "timeline_count": len(topic_page.timeline),
                "entities_count": len(topic_page.entities),
                "sources_count": len(topic_page.sources),
                "has_event_specific": any([topic_page.sports_data, topic_page.tech_data, topic_page.cultural_data, topic_page.business_data, topic_page.disaster_data]),
            }
        })

    # ── Step 5: Grounding / verification ──
    if from_step > 5:
        cp = ckpt.load(run_dir, 5)
        if cp:
            try:
                topic_page = TopicPage.model_validate(cp)
                yield _sse({
                    "step": 5, "status": "done", "elapsed_ms": 0, "from_checkpoint": True,
                    "result": verification_counts(topic_page),
                    "page": topic_page.model_dump(),
                })
            except Exception as e:
                logger.warning("Step 5 checkpoint invalid for run %s: %s, re-running", run_id, e)
                from_step = 5
        else:
            logger.warning("Step 5 checkpoint missing for run %s, re-running from step 5", run_id)
            from_step = 5

    if from_step <= 5:
        yield _sse({"step": 5, "status": "running", "elapsed_ms": 0})
        t0 = time.monotonic()
        try:
            topic_page = await verify_facts(topic_page, search_results, provider)
        except Exception as e:
            yield _sse({"step": 5, "status": "error", "elapsed_ms": _ms(t0), "error": str(e)})
            return

        ckpt.save(run_dir, 5, topic_page.model_dump())
        yield _sse({
            "step": 5, "status": "done", "elapsed_ms": _ms(t0),
            "result": verification_counts(topic_page),
            "page": topic_page.model_dump(),
        })

    # ── Step 6: Render HTML ──
    yield _sse({"step": 6, "status": "running", "elapsed_ms": 0})
    t0 = time.monotonic()
    try:
        html = await render_page(topic_page, provider)
    except Exception as e:
        yield _sse({"step": 6, "status": "error", "elapsed_ms": _ms(t0), "error": str(e)})
        return

    saved_path = save_page(topic_page, html, run_dir)
    logger.info("HTML saved: %s", saved_path)

    yield _sse({"step": 6, "status": "done", "elapsed_ms": _ms(t0), "html": html, "title": topic_page.title})
