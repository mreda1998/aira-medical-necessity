# Medical Necessity Checker

Upload a text-readable payer guideline PDF and a patient chart PDF. The app returns one of four outcomes:

- Meets medical necessity
- Does not meet criteria
- Incomplete evidence
- Policy not applicable

LLMs extract a structured policy tree and patient facts; they do not make the final decision. A deterministic, three-valued evaluator applies the guideline's nested `AND`, `OR`, and `N-of` logic and, when locally verifiable, links evidence back to its PDF page and section.

## Run locally

```bash
cp .env.example .env
# Add OPENAI_API_KEY and MISTRAL_API_KEY to .env
docker compose up --build
```

Open [http://localhost:8000](http://localhost:8000), then upload a guideline and chart.

## Architecture

The pipeline is payer-agnostic: each uploaded guideline is compiled into the same generic criteria-tree format. Florida Blue is a regression dataset, not a hard-coded ruleset; the same pipeline has also been exercised with Cigna and Anthem policies.

- OpenAI extracts the guideline tree, order, and chart facts as structured data.
- Python validates the tree, routes the case, and computes the verdict deterministically.
- Mistral re-checks only the evidence leaves that affected the verdict and cannot override it.
- The UI shows decisive findings plus satisfied criteria for unresolved and failing cases, while retaining the full evaluated tree in the API response.

See [DESIGN_NOTE.md](DESIGN_NOTE.md) for the concise architecture and failure-mode discussion, or [the full specification](docs/superpowers/specs/2026-07-15-medical-necessity-checker-design.md) for implementation detail.

## Tests

```bash
pip install -e ".[dev]"
pytest
```

The test suite covers extraction boundaries, policy routing, Boolean evaluation, evidence provenance, and API behavior. `advanced_prior_auth_test_pack` contains payer guidelines and synthetic patient charts for all four outcomes.

## Example results

### Meets medical necessity

<img width="1306" height="1634" alt="Meets medical necessity result" src="https://github.com/user-attachments/assets/459d4508-f9cb-4eee-9275-6c3456c5bf71" />

### Incomplete evidence

<img width="1320" height="1238" alt="Incomplete evidence result" src="https://github.com/user-attachments/assets/a80ba3ce-4f59-404d-8abc-a2ee7c1558b2" />

### Does not meet criteria

<img width="1316" height="1596" alt="Does not meet criteria result" src="https://github.com/user-attachments/assets/0114d647-d1e1-4964-8436-9ea7fe21b90c" />

### Policy not applicable

<img width="1286" height="806" alt="Policy not applicable result" src="https://github.com/user-attachments/assets/c1730555-8a6b-4b82-9fc1-8cd876579688" />
