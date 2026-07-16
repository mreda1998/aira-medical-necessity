import json
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, Depends, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError
from pypdf.errors import PdfReadError

from .llm import LLM, openai_client, mistral_client
from .pipeline import run, RunResult

app = FastAPI(title="Medical Necessity Checker")


def get_clients() -> tuple[LLM, LLM]:
    return openai_client(), mistral_client()


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.post("/api/evaluate", response_model=RunResult)
async def evaluate_endpoint(
    guideline: UploadFile = File(...),
    chart: UploadFile = File(...),
    clients: tuple[LLM, LLM] = Depends(get_clients),
):
    primary, verifier = clients
    guideline_bytes = await guideline.read()
    chart_bytes = await chart.read()
    try:
        return run(guideline_bytes, chart_bytes, primary, verifier)
    except ValidationError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"LLM output failed validation: {exc.errors()[0]['msg']}",
        ) from exc
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=502,
            detail="LLM returned malformed JSON",
        ) from exc
    except PdfReadError as exc:
        raise HTTPException(status_code=400, detail="could not read PDF input") from exc


_dist = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
if _dist.exists():
    app.mount("/", StaticFiles(directory=str(_dist), html=True), name="frontend")
