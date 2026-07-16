import json
import logging
import os
import sys
import time
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, Form, Depends, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError
from pypdf.errors import PdfReadError

from .llm import LLM, openai_client, mistral_client
from .pipeline import run, RunResult
from .trace import Tracer


def _configure_logging() -> None:
    """Send our ``aira.*`` logs to stdout so they show up in `docker compose logs`.

    We attach our own handler (rather than relying on uvicorn's root config) so
    the level and format are predictable regardless of how the server is launched.
    Set LOG_LEVEL=DEBUG to also log full LLM prompts and responses.
    """
    level = os.environ.get("LOG_LEVEL", "INFO").upper()
    logger = logging.getLogger("aira")
    logger.setLevel(level)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        logger.addHandler(handler)
    logger.propagate = False


_configure_logging()
log = logging.getLogger("aira.api")

app = FastAPI(title="Medical Necessity Checker")

DEBUG_DIR = Path(os.environ.get("DEBUG_DIR", "/data/debug"))


def get_clients() -> tuple[LLM, LLM]:
    return openai_client(), mistral_client()


def _debug_requested(flag: bool) -> bool:
    return flag or os.environ.get("AIRA_DEBUG", "").lower() in ("1", "true", "yes")


def _dump_trace(tracer: Tracer, run_id: str) -> Path:
    """Write one JSON file per pipeline step under DEBUG_DIR/<run_id>/ and return the dir."""
    out = DEBUG_DIR / run_id
    out.mkdir(parents=True, exist_ok=True)
    for i, step in enumerate(tracer.as_list()):
        (out / f"{i:02d}_{step['step'].replace(':', '_')}.json").write_text(
            json.dumps(step["data"], indent=2)
        )
    log.info("wrote %d debug step file(s) to %s", len(tracer.as_list()), out)
    return out


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.post("/api/evaluate", response_model=RunResult)
async def evaluate_endpoint(
    guideline: UploadFile = File(...),
    chart: UploadFile = File(...),
    debug: bool = Form(False),
    clients: tuple[LLM, LLM] = Depends(get_clients),
):
    primary, verifier = clients
    guideline_bytes = await guideline.read()
    chart_bytes = await chart.read()
    log.info(
        "evaluate: guideline=%s (%d B) chart=%s (%d B) debug=%s",
        guideline.filename,
        len(guideline_bytes),
        chart.filename,
        len(chart_bytes),
        _debug_requested(debug),
    )

    tracer = Tracer() if _debug_requested(debug) else None
    run_id = time.strftime("%Y%m%d-%H%M%S")
    try:
        return run(guideline_bytes, chart_bytes, primary, verifier, tracer)
    except ValidationError as exc:
        log.exception("evaluate failed: LLM output failed schema validation")
        raise HTTPException(
            status_code=502,
            detail=f"LLM output failed validation: {exc.errors()[0]['msg']}",
        ) from exc
    except json.JSONDecodeError as exc:
        log.exception("evaluate failed: LLM returned malformed JSON")
        raise HTTPException(status_code=502, detail="LLM returned malformed JSON") from exc
    except PdfReadError as exc:
        log.exception("evaluate failed: could not read PDF input")
        raise HTTPException(status_code=400, detail="could not read PDF input") from exc
    except Exception as exc:
        log.exception("evaluate failed: unexpected pipeline error")
        raise HTTPException(
            status_code=502,
            detail=f"pipeline failure: {type(exc).__name__}: {exc}",
        ) from exc
    finally:
        if tracer is not None:
            _dump_trace(tracer, run_id)


_dist = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
if _dist.exists():
    app.mount("/", StaticFiles(directory=str(_dist), html=True), name="frontend")
