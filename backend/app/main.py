import json
import logging
import os
import queue
import sys
import threading
import time
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, Form, Depends, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import StreamingResponse
from pydantic import ValidationError
from pypdf.errors import PdfReadError

from .llm import LLM, openai_client, mistral_client
from .pdf_extract import DocumentQualityError
from .pipeline import run, RunResult, ProgressUpdate
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
        return run(
            guideline_bytes,
            chart_bytes,
            primary,
            verifier,
            tracer,
            guideline_name=guideline.filename,
            chart_name=chart.filename,
        )
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
    except DocumentQualityError as exc:
        log.warning("evaluate rejected by document preflight: %s", exc)
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        log.exception("evaluate failed: unexpected pipeline error")
        raise HTTPException(
            status_code=502,
            detail=f"pipeline failure: {type(exc).__name__}: {exc}",
        ) from exc
    finally:
        if tracer is not None:
            _dump_trace(tracer, run_id)


def _stream_error(exc: Exception) -> tuple[int, str]:
    if isinstance(exc, ValidationError):
        return 502, f"LLM output failed validation: {exc.errors()[0]['msg']}"
    if isinstance(exc, json.JSONDecodeError):
        return 502, "LLM returned malformed JSON"
    if isinstance(exc, PdfReadError):
        return 400, "could not read PDF input"
    if isinstance(exc, DocumentQualityError):
        return 422, str(exc)
    return 502, f"pipeline failure: {type(exc).__name__}: {exc}"


@app.post("/api/evaluate/stream")
async def evaluate_stream_endpoint(
    guideline: UploadFile = File(...),
    chart: UploadFile = File(...),
    debug: bool = Form(False),
    clients: tuple[LLM, LLM] = Depends(get_clients),
):
    """Stream newline-delimited progress events followed by one result event."""
    primary, verifier = clients
    guideline_bytes = await guideline.read()
    chart_bytes = await chart.read()
    requested_debug = _debug_requested(debug)
    log.info(
        "evaluate stream: guideline=%s (%d B) chart=%s (%d B) debug=%s",
        guideline.filename,
        len(guideline_bytes),
        chart.filename,
        len(chart_bytes),
        requested_debug,
    )
    tracer = Tracer() if requested_debug else None
    run_id = time.strftime("%Y%m%d-%H%M%S")

    def event_stream():
        events: queue.Queue[dict | None] = queue.Queue()

        def publish(update: ProgressUpdate) -> None:
            events.put({"type": "progress", "progress": update.model_dump(mode="json")})

        def worker() -> None:
            try:
                result = run(
                    guideline_bytes,
                    chart_bytes,
                    primary,
                    verifier,
                    tracer,
                    guideline_name=guideline.filename,
                    chart_name=chart.filename,
                    progress=publish,
                )
                events.put({"type": "result", "result": result.model_dump(mode="json")})
            except Exception as exc:  # noqa: BLE001 - converted to a typed stream event
                status, detail = _stream_error(exc)
                log.exception("streamed evaluation failed: %s", detail)
                events.put({"type": "error", "status": status, "detail": detail})
            finally:
                if tracer is not None:
                    _dump_trace(tracer, run_id)
                events.put(None)

        threading.Thread(target=worker, daemon=True).start()
        while True:
            event = events.get()
            if event is None:
                break
            yield json.dumps(event, ensure_ascii=False) + "\n"

    return StreamingResponse(
        event_stream(),
        media_type="application/x-ndjson",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


_dist = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
if _dist.exists():
    app.mount("/", StaticFiles(directory=str(_dist), html=True), name="frontend")
