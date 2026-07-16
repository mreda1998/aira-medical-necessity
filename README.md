# Medical Necessity Checker

Reads a payer medical-necessity guideline PDF and a patient chart PDF, and returns a
prior-authorization verdict (MEETS / DOES NOT MEET / INCOMPLETE) with a gap list of exactly
what is missing. The decision is made by a deterministic rule engine; LLMs only extract structured
data from the PDFs.

## Run

```bash
cp .env.example .env      # paste your OPENAI_API_KEY and MISTRAL_API_KEY
docker compose up --build
```

Open http://localhost:8000, upload a guideline PDF and a chart PDF, and read the gap list.

## Design

See [DESIGN_NOTE.md](DESIGN_NOTE.md) (the short version: where the judgment lives and what breaks first) and `docs/superpowers/specs/2026-07-15-medical-necessity-checker-design.md` (full spec). In short: the LLM
compiles the guideline into a criteria tree (data) and extracts patient facts from the chart (data);
a pure-Python three-valued evaluator (code) produces the verdict. A second model re-verifies only
the leaves the verdict actually hinges on.

## Debugging a run

Every request logs its pipeline stages to stdout (visible in `docker compose logs -f`):
guideline compile, chart extraction, order routing, per-branch fact extraction, verifier
activity, and the final verdict. Failures log a full traceback and return a `502` whose
`detail` names the real error.

To capture the intermediate JSON at **every step** (compiled criteria tree, extracted order,
per-branch facts, verifier output, verdict tree):

- Per request: add the form field `debug=true` — the response gains a `debug` array, and one
  JSON file per step is written under `DEBUG_DIR` (default `/data/debug/<timestamp>/`).
- For all requests: set `AIRA_DEBUG=1` in `.env`.
- Set `LOG_LEVEL=DEBUG` to also log the full LLM prompts and responses.

```bash
# capture the full step-by-step trace for one chart
curl -s -F guideline=@guideline.pdf -F chart=@chart.pdf -F debug=true \
  http://localhost:8000/api/evaluate | jq '.debug[].step'
# the JSON artifacts land in the mounted volume:
docker compose exec app ls -R /data/debug
```

## Tests

```bash
pip install -e ".[dev]" && pytest
```
