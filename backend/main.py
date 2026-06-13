import os
import json
import logging
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

from pipeline import run_pipeline
from schemas.topic_page import TopicPage
from config import PROVIDER_MODELS
import checkpoints as ckpt

app = FastAPI(title="Topic Page Generator")


@app.on_event("startup")
async def _check_env():
    required = {
        "At least one LLM key": ["ANTHROPIC_API_KEY", "GOOGLE_API_KEY"],
        "Search key": ["TAVILY_API_KEY"],
    }
    for label, keys in required.items():
        if not any(os.getenv(k) for k in keys):
            logger.warning("%s is missing. Set one of: %s", label, ", ".join(keys))
        else:
            present = [k for k in keys if os.getenv(k)]
            logger.info("%s: %s", label, ", ".join(present))

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class GenerateRequest(BaseModel):
    sentence: str
    provider: str = "gemini"
    search_source: str = "tavily"
    run_id: Optional[str] = None
    from_step: int = 1


@app.post("/generate")
async def generate(request: GenerateRequest):
    if not request.sentence.strip():
        return {"error": "sentence is required"}

    if request.provider not in PROVIDER_MODELS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown provider '{request.provider}'. Options: {', '.join(PROVIDER_MODELS)}",
        )

    from_step = max(1, min(request.from_step, 6))

    return StreamingResponse(
        run_pipeline(
            sentence=request.sentence.strip(),
            provider=request.provider,
            search_source=request.search_source,
            run_id=request.run_id,
            from_step=from_step,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        }
    )


@app.post("/run/{run_id}/page")
async def update_page(run_id: str, page: TopicPage):
    """Editorial review surface: persist an edited TopicPage as the Step 5 checkpoint.

    The client then re-runs /generate with from_step=6 to re-render from the edited data.
    Edits happen on the structured model — never on the rendered HTML — so the data stays
    the source of truth and provenance/verification fields survive the round-trip.
    """
    run_dir = ckpt.get_or_create_run_dir(run_id)

    # First edit only: preserve the verifier's untouched output as step_5.original.json
    # so the pre-edit state survives repeated applies.
    current = run_dir / "checkpoints" / "step_5.json"
    original = run_dir / "checkpoints" / "step_5.original.json"
    if current.exists() and not original.exists():
        original.write_text(current.read_text())
        logger.info("Backed up pre-edit checkpoint to %s", original)

    ckpt.save(run_dir, 5, page.model_dump())
    logger.info("Edited TopicPage saved as Step 5 checkpoint for run %s", run_id)
    return {"status": "ok", "run_id": run_id, "has_original": original.exists()}


@app.get("/run/{run_id}/page/original")
async def get_original_page(run_id: str):
    """Serve the verifier's pre-edit output (step_5.original.json). Read-only: the
    client loads it back into the review form; committing it goes through the normal
    edit endpoint (user clicks Apply to save + re-render)."""
    run_dir = ckpt.get_or_create_run_dir(run_id)
    original = run_dir / "checkpoints" / "step_5.original.json"
    if not original.exists():
        raise HTTPException(status_code=404, detail="No pre-edit checkpoint exists")
    return json.loads(original.read_text())


@app.get("/health")
async def health():
    return {"status": "ok"}
