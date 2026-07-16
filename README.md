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

## Tests

```bash
pip install -e ".[dev]" && pytest
```
