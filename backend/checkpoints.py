import json
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent
OUTPUT_DIR = BASE_DIR / "output"


def get_or_create_run_dir(run_id: str) -> Path:
    """Return the run directory for run_id.

    On resume: searches output/*/{run_id} and returns the existing dir.
    On new run: creates output/{MMDD-HHMM}/{run_id}/ and returns it.
    """
    for candidate in OUTPUT_DIR.glob(f"*/{run_id}"):
        if candidate.is_dir():
            logger.info("Found existing run dir: %s", candidate)
            return candidate

    timestamp = datetime.now().strftime("%m%d-%H%M")
    run_dir = OUTPUT_DIR / timestamp / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    logger.info("Created run dir: %s", run_dir)
    return run_dir


def save(run_dir: Path, step: int, data: dict) -> None:
    ckpt_dir = run_dir / "checkpoints"
    ckpt_dir.mkdir(parents=True, exist_ok=True)
    path = ckpt_dir / f"step_{step}.json"
    path.write_text(json.dumps(data, ensure_ascii=False))
    logger.info("Checkpoint saved: %s", path)


def load(run_dir: Path, step: int) -> Optional[dict]:
    path = run_dir / "checkpoints" / f"step_{step}.json"
    if not path.exists():
        logger.warning("Checkpoint missing: %s", path)
        return None
    data = json.loads(path.read_text())
    logger.info("Checkpoint loaded: %s", path)
    return data
