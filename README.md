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
I have added tests for every step of the process, we also generated patients data that can be matched against different verdicts (MEETS / DOES NOT MEET / INCOMPLETE). Those are present under the folder advanced_prior_auth_test_pack and other guidelines from Florida Blue were also integrated for testing purposes.
```bash
pip install -e ".[dev]" && pytest
```
Scenario 1: Patient Meets 
<img width="1306" height="1634" alt="image" src="https://github.com/user-attachments/assets/459d4508-f9cb-4eee-9275-6c3456c5bf71" />

Scenario 2: Incomplete Evidence
<img width="1320" height="1238" alt="image" src="https://github.com/user-attachments/assets/a80ba3ce-4f59-404d-8abc-a2ee7c1558b2" />

Scenario 3: Does Not Meet
<img width="1316" height="1596" alt="image" src="https://github.com/user-attachments/assets/0114d647-d1e1-4964-8436-9ea7fe21b90c" />

Scenario 4: Policy Not Applicable
<img width="1286" height="806" alt="image" src="https://github.com/user-attachments/assets/c1730555-8a6b-4b82-9fc1-8cd876579688" />





