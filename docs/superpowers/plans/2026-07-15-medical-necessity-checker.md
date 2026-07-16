# Medical Necessity Checker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an MVP that takes a payer guideline PDF and a patient chart PDF and returns a medical-necessity verdict plus a gap list of exactly what is missing, driven by a deterministic rule engine with LLMs confined to extraction.

**Architecture:** LLMs compile the guideline PDF into a structured criteria tree (data) and extract patient facts from the chart (data). A pure-Python three-valued evaluator (code) walks the tree against the facts and returns MET / NOT_MET / INSUFFICIENT_EVIDENCE with a full trace. A second LLM re-verifies only verdict-pivotal or low-confidence leaves. FastAPI serves the pipeline; a small React SPA is the UI.

**Tech Stack:** Python 3.11, FastAPI, Pydantic v2, pypdf, openai + mistralai SDKs, pytest; React + Vite + TypeScript; Docker Compose.

## Global Constraints

- Nothing about varicose veins may be hardcoded — the evaluator is guideline-agnostic and operates only on the generic criteria-tree schema.
- No LLM produces the final verdict. LLMs only extract/normalize at defined boundaries.
- Must run on a clean checkout from one command: `docker compose up`. API keys via `.env`.
- Three verdict states everywhere: `MET`, `NOT_MET`, `INSUFFICIENT_EVIDENCE`.
- Every leaf carries a guideline `source_span`; every fact carries a chart `source_span` or `found: false`.
- Primary LLM = OpenAI; verifier LLM = Mistral. Provider/model swappable via env.
- Python: use `pytest`. Format with the repo default; no unrelated refactors.
- No Postgres. Compiled guideline trees are cached as JSON on disk keyed by content hash.

---

## File Structure

```
aira-medical-necessity/
├── docker-compose.yml
├── Dockerfile
├── .env.example
├── README.md
├── pyproject.toml
├── backend/
│   └── app/
│       ├── __init__.py
│       ├── models.py          # Pydantic schemas: tree nodes, Fact, EvalResult, Order
│       ├── reference.py       # CEAP ordinal, vein synonyms, measurement parsing
│       ├── evaluator.py       # PURE three-valued engine + pivotality
│       ├── pdf_extract.py     # pypdf → text
│       ├── llm.py             # provider abstraction (openai/mistral) + mockable Client
│       ├── compiler.py        # guideline text → CriteriaTree (LLM) + disk cache
│       ├── router.py          # order extraction (LLM) + branch selection (code)
│       ├── extractor.py       # guided chart fact extraction (LLM)
│       ├── verifier.py        # 2nd-LLM recheck of pivotal/low-conf leaves
│       ├── pipeline.py        # orchestration: run(guideline, chart) → RunResult
│       ├── store.py           # disk cache for compiled guidelines
│       └── main.py            # FastAPI app
│   └── tests/
│       ├── conftest.py
│       ├── test_models.py
│       ├── test_reference.py
│       ├── test_evaluator.py
│       ├── test_router.py
│       ├── test_compiler.py
│       ├── test_extractor.py
│       ├── test_verifier.py
│       └── test_pipeline.py
└── frontend/
    ├── package.json
    ├── vite.config.ts
    ├── index.html
    └── src/{main.tsx, App.tsx, api.ts, components/GapList.tsx}
```

---

### Task 1: Project scaffold + schema models

**Files:**
- Create: `pyproject.toml`, `backend/app/__init__.py`, `backend/app/models.py`, `backend/tests/__init__.py`, `backend/tests/test_models.py`

**Interfaces:**
- Produces: `Status` (enum: `MET`, `NOT_MET`, `INSUFFICIENT`), `PredicateType` enum, `SourceSpan`, `LeafNode`, `UnmappableNode`, `AllOf`, `AnyOf`, `NOf`, `Node` (union), `CriteriaBranch`, `CriteriaTree`, `Fact`, `Order`, `EvalResult`.

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[project]
name = "aira-medical-necessity"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.110",
    "uvicorn[standard]>=0.29",
    "pydantic>=2.6",
    "python-multipart>=0.0.9",
    "pypdf>=4.0",
    "openai>=1.30",
    "mistralai>=1.0",
]

[project.optional-dependencies]
dev = ["pytest>=8.0", "httpx>=0.27"]

[tool.pytest.ini_options]
pythonpath = ["backend"]
testpaths = ["backend/tests"]
```

- [ ] **Step 2: Write the failing test** — `backend/tests/test_models.py`

```python
from app.models import (
    Status, PredicateType, LeafNode, AllOf, NOf, CriteriaTree,
    CriteriaBranch, Fact, Order,
)


def test_leaf_node_roundtrips():
    leaf = LeafNode(
        id="l1", predicate=PredicateType.NUMERIC_GTE, field="vein_diameter_mm",
        threshold=3, unit="mm", human_readable="Varicosities at least 3 mm",
    )
    assert leaf.kind == "leaf"
    assert LeafNode.model_validate(leaf.model_dump()).threshold == 3


def test_tree_with_nested_nodes_parses_from_dict():
    tree = CriteriaTree.model_validate({
        "guideline_id": "02-33000-31",
        "title": "Varicose Veins",
        "branches": [{
            "branch_id": "great_or_small_saphenous",
            "vein_types": ["great_saphenous", "small_saphenous"],
            "procedure_label": "Treatment of great or small saphenous veins",
            "root": {
                "kind": "all_of", "id": "root", "children": [
                    {"kind": "leaf", "id": "reflux", "predicate": "boolean",
                     "field": "saphenous_reflux_demonstrated", "threshold": True,
                     "human_readable": "Demonstrated saphenous reflux"},
                    {"kind": "n_of", "id": "indications", "k": 1, "children": [
                        {"kind": "leaf", "id": "ulcer", "predicate": "existence",
                         "field": "venous_stasis_ulcer", "human_readable": "Ulceration"},
                    ]},
                ],
            },
        }],
    })
    assert tree.branches[0].root.kind == "all_of"
    assert tree.branches[0].root.children[1].k == 1


def test_status_and_order():
    assert Status.INSUFFICIENT.value == "INSUFFICIENT_EVIDENCE"
    o = Order(modality="radiofrequency", vein="great_saphenous", laterality="right", cpt="36475")
    assert o.vein == "great_saphenous"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest backend/tests/test_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.models'`

- [ ] **Step 4: Write `backend/app/models.py`**

```python
from __future__ import annotations

from enum import Enum
from typing import Literal, Optional, Union

from pydantic import BaseModel


class Status(str, Enum):
    MET = "MET"
    NOT_MET = "NOT_MET"
    INSUFFICIENT = "INSUFFICIENT_EVIDENCE"


class PredicateType(str, Enum):
    BOOLEAN = "boolean"
    NUMERIC_GTE = "numeric_gte"
    NUMERIC_LTE = "numeric_lte"
    ORDINAL_GTE = "ordinal_gte"
    DURATION_GTE = "duration_gte"
    EXISTENCE = "existence"


class SourceSpan(BaseModel):
    text: str
    page: Optional[int] = None


class LeafNode(BaseModel):
    kind: Literal["leaf"] = "leaf"
    id: str
    predicate: PredicateType
    field: str
    threshold: Optional[Union[float, str, bool]] = None
    unit: Optional[str] = None
    negated: bool = False
    human_readable: str
    source_span: Optional[SourceSpan] = None
    parse_confidence: float = 1.0


class UnmappableNode(BaseModel):
    kind: Literal["unmappable"] = "unmappable"
    id: str
    human_readable: str
    reason: str = ""
    source_span: Optional[SourceSpan] = None


class AllOf(BaseModel):
    kind: Literal["all_of"] = "all_of"
    id: str
    children: list["Node"]


class AnyOf(BaseModel):
    kind: Literal["any_of"] = "any_of"
    id: str
    children: list["Node"]


class NOf(BaseModel):
    kind: Literal["n_of"] = "n_of"
    id: str
    k: int
    children: list["Node"]


Node = Union[AllOf, AnyOf, NOf, LeafNode, UnmappableNode]


class CriteriaBranch(BaseModel):
    branch_id: str
    vein_types: list[str]
    procedure_label: str
    root: Node


class CriteriaTree(BaseModel):
    guideline_id: str
    title: str
    branches: list[CriteriaBranch]


class Fact(BaseModel):
    field: str
    value: Optional[Union[float, str, bool]] = None
    unit: Optional[str] = None
    found: bool = False
    source_span: Optional[SourceSpan] = None
    confidence: float = 1.0


class Order(BaseModel):
    modality: Optional[str] = None
    vein: Optional[str] = None
    laterality: Optional[str] = None
    cpt: Optional[str] = None
    raw: Optional[str] = None


class EvalResult(BaseModel):
    node_id: str
    kind: str
    status: Status
    human_readable: Optional[str] = None
    field: Optional[str] = None
    evidence: Optional[Fact] = None
    guideline_span: Optional[SourceSpan] = None
    flags: list[str] = []
    children: list["EvalResult"] = []


for _m in (AllOf, AnyOf, NOf, CriteriaBranch, EvalResult):
    _m.model_rebuild()
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest backend/tests/test_models.py -v`
Expected: PASS (3 tests)

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml backend/app/__init__.py backend/app/models.py backend/tests/__init__.py backend/tests/test_models.py
git commit -m "feat: add schema models for criteria tree, facts, verdicts"
```

---

### Task 2: Reference layer (CEAP ordinal, vein synonyms, measurement parsing)

**Files:**
- Create: `backend/app/reference.py`, `backend/tests/test_reference.py`

**Interfaces:**
- Produces:
  - `compare_ordinal(a: str, b: str) -> int` — sign of rank(a) - rank(b); raises `ValueError` on unknown class.
  - `parse_measurement(value) -> float | None` — lower bound of ranges ("3-4 mm" → 3.0), conservative.
  - `canonical_vein(name: str) -> str | None` — synonym → canonical vein id.

- [ ] **Step 1: Write the failing test** — `backend/tests/test_reference.py`

```python
import pytest
from app.reference import compare_ordinal, parse_measurement, canonical_vein


def test_ceap_ordering():
    assert compare_ordinal("C3", "C2") > 0
    assert compare_ordinal("C2", "C2") == 0
    assert compare_ordinal("C1", "C2") < 0
    assert compare_ordinal("C2r", "C2") > 0  # recurrent ranks above C2


def test_ceap_unknown_raises():
    with pytest.raises(ValueError):
        compare_ordinal("C9", "C2")


def test_parse_measurement_takes_lower_bound():
    assert parse_measurement("3 mm") == 3.0
    assert parse_measurement("3-4 mm") == 3.0     # conservative
    assert parse_measurement("3.5") == 3.5
    assert parse_measurement("no measurement") is None


def test_vein_synonyms():
    assert canonical_vein("GSV") == "great_saphenous"
    assert canonical_vein("great saphenous vein") == "great_saphenous"
    assert canonical_vein("long saphenous") == "great_saphenous"
    assert canonical_vein("unknown vein") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_reference.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write `backend/app/reference.py`**

```python
import re
from typing import Optional

CEAP_ORDER = ["C0", "C1", "C2", "C2R", "C3", "C4A", "C4B", "C4C", "C5", "C6", "C6R"]


def _ceap_rank(v: str) -> int:
    key = v.strip().upper().rstrip("SA")  # drop trailing symptomatic/asymptomatic marker
    if key not in CEAP_ORDER:
        # tolerate C4 without subletter by mapping to C4A
        if key == "C4":
            key = "C4A"
        else:
            raise ValueError(f"unknown CEAP class: {v!r}")
    return CEAP_ORDER.index(key)


def compare_ordinal(a: str, b: str) -> int:
    ra, rb = _ceap_rank(a), _ceap_rank(b)
    return (ra > rb) - (ra < rb)


def parse_measurement(value) -> Optional[float]:
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        return None
    nums = re.findall(r"\d+(?:\.\d+)?", value)
    if not nums:
        return None
    return min(float(n) for n in nums)  # lower bound = conservative


_VEIN_SYNONYMS = {
    "great_saphenous": ["gsv", "great saphenous", "long saphenous", "large saphenous"],
    "small_saphenous": ["ssv", "small saphenous", "short saphenous", "lesser saphenous"],
    "accessory_saphenous": ["asv", "accessory saphenous", "anterior accessory saphenous"],
    "perforator": ["perforator", "perforating vein"],
    "tributary": ["tributary", "varicose tributary"],
}


def canonical_vein(name: str) -> Optional[str]:
    n = name.strip().lower().replace(" vein", "")
    for canon, syns in _VEIN_SYNONYMS.items():
        for s in syns:
            if s.replace(" vein", "") in n:
                return canon
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/tests/test_reference.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/reference.py backend/tests/test_reference.py
git commit -m "feat: add reference layer for CEAP ordinal, vein synonyms, measurements"
```

---

### Task 3: Evaluator — three-valued engine + pivotality (the core)

**Files:**
- Create: `backend/app/evaluator.py`, `backend/tests/test_evaluator.py`

**Interfaces:**
- Consumes: `models`, `reference.compare_ordinal`, `reference.parse_measurement`.
- Produces:
  - `evaluate(node: Node, facts: dict[str, Fact], overrides: dict[str, Status] | None = None) -> EvalResult`
  - `pivotal_leaf_ids(root: Node, facts: dict[str, Fact]) -> list[str]` — leaves whose forced MET vs NOT_MET flips the root status.

- [ ] **Step 1: Write the failing test** — `backend/tests/test_evaluator.py`

```python
from app.models import (
    Status, PredicateType, LeafNode, AllOf, AnyOf, NOf, Fact,
)
from app.evaluator import evaluate, pivotal_leaf_ids


def leaf(id, pred, field, threshold=None, negated=False):
    return LeafNode(id=id, predicate=pred, field=field, threshold=threshold,
                    negated=negated, human_readable=id)


def fact(field, value=None, found=True):
    return Fact(field=field, value=value, found=found)


def facts(*fs):
    return {f.field: f for f in fs}


def test_leaf_met_not_met_insufficient():
    l = leaf("d", PredicateType.NUMERIC_GTE, "vein_diameter_mm", 3)
    assert evaluate(l, facts(fact("vein_diameter_mm", 4))).status == Status.MET
    assert evaluate(l, facts(fact("vein_diameter_mm", 2))).status == Status.NOT_MET
    assert evaluate(l, {}).status == Status.INSUFFICIENT


def test_ordinal_leaf():
    l = leaf("c", PredicateType.ORDINAL_GTE, "ceap_class", "C2")
    assert evaluate(l, facts(fact("ceap_class", "C3"))).status == Status.MET
    assert evaluate(l, facts(fact("ceap_class", "C1"))).status == Status.NOT_MET


def test_negated_leaf():
    l = leaf("dvt", PredicateType.BOOLEAN, "insufficiency_secondary_to_dvt",
             threshold=True, negated=True)
    assert evaluate(l, facts(fact("insufficiency_secondary_to_dvt", True))).status == Status.NOT_MET
    assert evaluate(l, facts(fact("insufficiency_secondary_to_dvt", False))).status == Status.MET


def test_all_of_precedence():
    node = AllOf(id="r", children=[
        leaf("a", PredicateType.BOOLEAN, "a", True),
        leaf("b", PredicateType.BOOLEAN, "b", True),
    ])
    assert evaluate(node, facts(fact("a", True), fact("b", True))).status == Status.MET
    assert evaluate(node, facts(fact("a", True), fact("b", False))).status == Status.NOT_MET
    assert evaluate(node, facts(fact("a", True))).status == Status.INSUFFICIENT  # b missing


def test_any_of_precedence():
    node = AnyOf(id="r", children=[
        leaf("a", PredicateType.BOOLEAN, "a", True),
        leaf("b", PredicateType.BOOLEAN, "b", True),
    ])
    assert evaluate(node, facts(fact("a", True))).status == Status.MET
    assert evaluate(node, facts(fact("a", False), fact("b", False))).status == Status.NOT_MET
    assert evaluate(node, {}).status == Status.INSUFFICIENT


def test_n_of_unreachable_is_not_met():
    node = NOf(id="r", k=2, children=[
        leaf("a", PredicateType.BOOLEAN, "a", True),
        leaf("b", PredicateType.BOOLEAN, "b", True),
        leaf("c", PredicateType.BOOLEAN, "c", True),
    ])
    # one MET, two NOT_MET → can't reach 2 → NOT_MET
    assert evaluate(node, facts(fact("a", True), fact("b", False), fact("c", False))).status == Status.NOT_MET
    # one MET, one missing → 1 MET + 1 INSUFFICIENT >= 2 possible → INSUFFICIENT
    assert evaluate(node, facts(fact("a", True), fact("b", False))).status == Status.INSUFFICIENT
    # two MET → MET
    assert evaluate(node, facts(fact("a", True), fact("b", True))).status == Status.MET


def test_pivotal_leaf_detection():
    # root = all_of(a, b); a is MET, b is missing → b is pivotal, a is not.
    node = AllOf(id="r", children=[
        leaf("a", PredicateType.BOOLEAN, "a", True),
        leaf("b", PredicateType.BOOLEAN, "b", True),
    ])
    ids = pivotal_leaf_ids(node, facts(fact("a", True)))
    assert "b" in ids
    assert "a" not in ids
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_evaluator.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write `backend/app/evaluator.py`**

```python
from typing import Optional

from .models import (
    Status, PredicateType, Node, LeafNode, UnmappableNode, AllOf, AnyOf, NOf,
    Fact, EvalResult,
)
from .reference import compare_ordinal, parse_measurement


def _apply_predicate(leaf: LeafNode, f: Fact) -> Status:
    p = leaf.predicate
    v = f.value
    if p == PredicateType.EXISTENCE:
        return Status.MET  # found is already true when we reach here
    if p == PredicateType.BOOLEAN:
        want = leaf.threshold if leaf.threshold is not None else True
        return Status.MET if bool(v) == bool(want) else Status.NOT_MET
    if p in (PredicateType.NUMERIC_GTE, PredicateType.NUMERIC_LTE, PredicateType.DURATION_GTE):
        num = parse_measurement(v)
        thr = parse_measurement(leaf.threshold)
        if num is None or thr is None:
            return Status.INSUFFICIENT
        if p == PredicateType.NUMERIC_LTE:
            return Status.MET if num <= thr else Status.NOT_MET
        return Status.MET if num >= thr else Status.NOT_MET  # gte / duration_gte
    if p == PredicateType.ORDINAL_GTE:
        try:
            return Status.MET if compare_ordinal(str(v), str(leaf.threshold)) >= 0 else Status.NOT_MET
        except ValueError:
            return Status.INSUFFICIENT
    return Status.INSUFFICIENT


def _eval_leaf(leaf: LeafNode, facts: dict[str, Fact]) -> EvalResult:
    f = facts.get(leaf.field)
    flags = []
    if leaf.parse_confidence < 0.6:
        flags.append("low_parse_confidence")
    if f is None or not f.found or (f.value is None and leaf.predicate != PredicateType.EXISTENCE):
        status = Status.INSUFFICIENT
    else:
        status = _apply_predicate(leaf, f)
        if leaf.negated and status in (Status.MET, Status.NOT_MET):
            status = Status.NOT_MET if status == Status.MET else Status.MET
    return EvalResult(
        node_id=leaf.id, kind="leaf", status=status, human_readable=leaf.human_readable,
        field=leaf.field, evidence=f, guideline_span=leaf.source_span, flags=flags,
    )


def _combine_all(sts: list[Status]) -> Status:
    if Status.NOT_MET in sts:
        return Status.NOT_MET
    if Status.INSUFFICIENT in sts:
        return Status.INSUFFICIENT
    return Status.MET


def _combine_any(sts: list[Status]) -> Status:
    if Status.MET in sts:
        return Status.MET
    if Status.INSUFFICIENT in sts:
        return Status.INSUFFICIENT
    return Status.NOT_MET


def _combine_n(sts: list[Status], k: int) -> Status:
    met = sts.count(Status.MET)
    ins = sts.count(Status.INSUFFICIENT)
    if met >= k:
        return Status.MET
    if met + ins < k:
        return Status.NOT_MET
    return Status.INSUFFICIENT


def evaluate(node: Node, facts: dict[str, Fact],
             overrides: Optional[dict[str, Status]] = None) -> EvalResult:
    overrides = overrides or {}
    if isinstance(node, LeafNode):
        if node.id in overrides:
            r = _eval_leaf(node, facts)
            r.status = overrides[node.id]
            return r
        return _eval_leaf(node, facts)
    if isinstance(node, UnmappableNode):
        return EvalResult(node_id=node.id, kind="unmappable", status=Status.INSUFFICIENT,
                          human_readable=node.human_readable, guideline_span=node.source_span,
                          flags=["unmappable"])
    child_results = [evaluate(c, facts, overrides) for c in node.children]
    sts = [c.status for c in child_results]
    if isinstance(node, AllOf):
        status = _combine_all(sts)
    elif isinstance(node, AnyOf):
        status = _combine_any(sts)
    elif isinstance(node, NOf):
        status = _combine_n(sts, node.k)
    else:
        raise TypeError(f"unknown node type: {type(node)}")
    return EvalResult(node_id=node.id, kind=node.kind, status=status, children=child_results)


def _collect_leaf_ids(node: Node) -> list[str]:
    if isinstance(node, (LeafNode, UnmappableNode)):
        return [node.id]
    ids = []
    for c in node.children:
        ids.extend(_collect_leaf_ids(c))
    return ids


def pivotal_leaf_ids(root: Node, facts: dict[str, Fact]) -> list[str]:
    base = evaluate(root, facts).status
    pivotal = []
    for lid in _collect_leaf_ids(root):
        forced_met = evaluate(root, facts, {lid: Status.MET}).status
        forced_not = evaluate(root, facts, {lid: Status.NOT_MET}).status
        if forced_met != forced_not or forced_met != base or forced_not != base:
            pivotal.append(lid)
    return pivotal
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/tests/test_evaluator.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/evaluator.py backend/tests/test_evaluator.py
git commit -m "feat: add deterministic three-valued evaluator and pivotality detection"
```

---

### Task 4: PDF text extraction

**Files:**
- Create: `backend/app/pdf_extract.py`, `backend/tests/test_pdf_extract.py`

**Interfaces:**
- Produces: `extract_text(data: bytes) -> str` — concatenated page text from PDF bytes.

- [ ] **Step 1: Write the failing test** — `backend/tests/test_pdf_extract.py`

```python
from pathlib import Path
import pytest
from app.pdf_extract import extract_text

SAMPLES = Path(__file__).parent / "samples"


@pytest.mark.skipif(not (SAMPLES / "guideline.pdf").exists(), reason="sample PDF not present")
def test_extract_text_from_guideline():
    data = (SAMPLES / "guideline.pdf").read_bytes()
    text = extract_text(data)
    assert "medical necessity" in text.lower()
    assert len(text) > 1000
```

- [ ] **Step 2: Add the sample PDFs**

```bash
mkdir -p backend/tests/samples
cp /Users/redar/Desktop/mcg.pdf backend/tests/samples/guideline.pdf
# copy the provided robert_mitchell chart if available:
# cp /path/to/robert_mitchell_chart_final.pdf backend/tests/samples/chart.pdf
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest backend/tests/test_pdf_extract.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 4: Write `backend/app/pdf_extract.py`**

```python
import io
from pypdf import PdfReader


def extract_text(data: bytes) -> str:
    reader = PdfReader(io.BytesIO(data))
    parts = []
    for page in reader.pages:
        parts.append(page.extract_text() or "")
    return "\n".join(parts)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest backend/tests/test_pdf_extract.py -v`
Expected: PASS (1 test)

- [ ] **Step 6: Commit**

```bash
git add backend/app/pdf_extract.py backend/tests/test_pdf_extract.py backend/tests/samples/guideline.pdf
git commit -m "feat: add pypdf text extraction"
```

---

### Task 5: LLM provider abstraction

**Files:**
- Create: `backend/app/llm.py`, `backend/tests/test_llm.py`

**Interfaces:**
- Produces:
  - `class LLMClient` with `complete_json(system: str, user: str, *, model: str | None = None) -> dict` — returns parsed JSON from the model. Uses OpenAI by default.
  - `openai_client()`, `mistral_client()` factory functions reading env `OPENAI_API_KEY` / `MISTRAL_API_KEY` and `PRIMARY_MODEL` / `VERIFIER_MODEL`.
  - A `FakeLLM` test double implementing `complete_json` from a queue of canned dicts.

- [ ] **Step 1: Write the failing test** — `backend/tests/test_llm.py`

```python
from app.llm import FakeLLM


def test_fake_llm_returns_queued_json():
    fake = FakeLLM([{"a": 1}, {"b": 2}])
    assert fake.complete_json("sys", "u1") == {"a": 1}
    assert fake.complete_json("sys", "u2") == {"b": 2}
    assert fake.calls[0]["user"] == "u1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_llm.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write `backend/app/llm.py`**

```python
import json
import os
from typing import Optional, Protocol


class LLM(Protocol):
    def complete_json(self, system: str, user: str, *, model: Optional[str] = None) -> dict: ...


class OpenAILLM:
    def __init__(self, model: Optional[str] = None):
        from openai import OpenAI
        self._client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
        self._model = model or os.environ.get("PRIMARY_MODEL", "gpt-4o")

    def complete_json(self, system: str, user: str, *, model: Optional[str] = None) -> dict:
        resp = self._client.chat.completions.create(
            model=model or self._model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            response_format={"type": "json_object"},
            temperature=0,
        )
        return json.loads(resp.choices[0].message.content)


class MistralLLM:
    def __init__(self, model: Optional[str] = None):
        from mistralai import Mistral
        self._client = Mistral(api_key=os.environ["MISTRAL_API_KEY"])
        self._model = model or os.environ.get("VERIFIER_MODEL", "mistral-large-latest")

    def complete_json(self, system: str, user: str, *, model: Optional[str] = None) -> dict:
        resp = self._client.chat.complete(
            model=model or self._model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            response_format={"type": "json_object"},
            temperature=0,
        )
        return json.loads(resp.choices[0].message.content)


class FakeLLM:
    """Test double: returns queued dicts in order, records calls."""

    def __init__(self, responses: list[dict]):
        self._responses = list(responses)
        self.calls: list[dict] = []

    def complete_json(self, system: str, user: str, *, model: Optional[str] = None) -> dict:
        self.calls.append({"system": system, "user": user, "model": model})
        return self._responses.pop(0)


def openai_client() -> OpenAILLM:
    return OpenAILLM()


def mistral_client() -> MistralLLM:
    return MistralLLM()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/tests/test_llm.py -v`
Expected: PASS (1 test)

- [ ] **Step 5: Commit**

```bash
git add backend/app/llm.py backend/tests/test_llm.py
git commit -m "feat: add LLM provider abstraction with OpenAI/Mistral and FakeLLM"
```

---

### Task 6: Guideline Compiler + disk cache

**Files:**
- Create: `backend/app/store.py`, `backend/app/compiler.py`, `backend/tests/test_compiler.py`

**Interfaces:**
- Consumes: `LLM`, `models.CriteriaTree`.
- Produces:
  - `store.tree_path(content_hash: str) -> Path`, `store.save_tree`, `store.load_tree(hash) -> CriteriaTree | None`.
  - `compiler.compile_guideline(text: str, llm: LLM) -> CriteriaTree` — prompts the LLM to emit the tree JSON, validates it into `CriteriaTree`. Nodes it cannot map become `unmappable`.
  - `compiler.compile_cached(data: bytes, llm: LLM) -> CriteriaTree` — hash → load or compile+save.

- [ ] **Step 1: Write the failing test** — `backend/tests/test_compiler.py`

```python
from app.llm import FakeLLM
from app.compiler import compile_guideline, COMPILER_SYSTEM
from app.models import CriteriaTree

TREE_JSON = {
    "guideline_id": "02-33000-31",
    "title": "Varicose Veins",
    "branches": [{
        "branch_id": "great_or_small_saphenous",
        "vein_types": ["great_saphenous", "small_saphenous"],
        "procedure_label": "Treatment of great or small saphenous veins",
        "root": {"kind": "all_of", "id": "root", "children": [
            {"kind": "leaf", "id": "reflux", "predicate": "boolean",
             "field": "saphenous_reflux_demonstrated", "threshold": True,
             "human_readable": "Demonstrated saphenous reflux"},
        ]},
    }],
}


def test_compile_guideline_validates_tree():
    fake = FakeLLM([TREE_JSON])
    tree = compile_guideline("some guideline text", fake)
    assert isinstance(tree, CriteriaTree)
    assert tree.branches[0].vein_types == ["great_saphenous", "small_saphenous"]
    # prompt actually included the guideline text
    assert "some guideline text" in fake.calls[0]["user"]
    assert "closed" in COMPILER_SYSTEM.lower()  # instructs the closed predicate vocabulary
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_compiler.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write `backend/app/store.py`**

```python
import hashlib
import json
from pathlib import Path
from typing import Optional

from .models import CriteriaTree

CACHE_DIR = Path(os.environ.get("CACHE_DIR", "/data/guidelines")) if (os := __import__("os")) else Path("/data/guidelines")


def content_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


def tree_path(h: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / f"{h}.json"


def save_tree(h: str, tree: CriteriaTree) -> None:
    tree_path(h).write_text(tree.model_dump_json(indent=2))


def load_tree(h: str) -> Optional[CriteriaTree]:
    p = tree_path(h)
    if not p.exists():
        return None
    return CriteriaTree.model_validate_json(p.read_text())
```

Note: fix the messy import line above to a clean `import os` at top; final file:

```python
import hashlib
import os
from pathlib import Path
from typing import Optional

from .models import CriteriaTree

CACHE_DIR = Path(os.environ.get("CACHE_DIR", "/data/guidelines"))


def content_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


def tree_path(h: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / f"{h}.json"


def save_tree(h: str, tree: CriteriaTree) -> None:
    tree_path(h).write_text(tree.model_dump_json(indent=2))


def load_tree(h: str) -> Optional[CriteriaTree]:
    p = tree_path(h)
    return CriteriaTree.model_validate_json(p.read_text()) if p.exists() else None
```

- [ ] **Step 4: Write `backend/app/compiler.py`**

```python
from .llm import LLM
from .models import CriteriaTree
from .pdf_extract import extract_text
from . import store

COMPILER_SYSTEM = """You convert a payer medical-necessity guideline into a structured criteria tree.
Output JSON only, matching this schema:
{ "guideline_id": str, "title": str, "branches": [ {
    "branch_id": str, "vein_types": [str], "procedure_label": str, "root": <node> } ] }

A <node> is one of:
  {"kind":"all_of","id":str,"children":[<node>...]}   (ALL must hold)
  {"kind":"any_of","id":str,"children":[<node>...]}   (ANY holds)
  {"kind":"n_of","id":str,"k":int,"children":[<node>...]}  (at least k hold)
  {"kind":"leaf","id":str,"predicate":P,"field":str,"threshold":<val>,"unit":str?,
   "negated":bool?,"human_readable":str,"source_span":{"text":str},"parse_confidence":float}
  {"kind":"unmappable","id":str,"human_readable":str,"reason":str,"source_span":{"text":str}}

P (the CLOSED predicate vocabulary — you MUST use only these) is one of:
  "boolean" | "numeric_gte" | "numeric_lte" | "ordinal_gte" | "duration_gte" | "existence"

Rules:
- Use canonical snake_case vein ids in vein_types: great_saphenous, small_saphenous,
  accessory_saphenous, perforator, tributary.
- "one or more of the following" -> n_of with k=1.
- Durations like "at least 3 months" -> duration_gte with field in months, threshold 3.
- CEAP class checks -> ordinal_gte with field "ceap_class", threshold like "C2".
- Vein size "at least 3 mm" -> numeric_gte, field "vein_diameter_mm", threshold 3, unit "mm".
- Cosmetic / experimental / investigational branches: still emit the branch, but its criteria
  are structurally unmeetable — model them faithfully.
- If a criterion cannot be expressed with the closed vocabulary, emit an "unmappable" node with a
  reason. NEVER invent a predicate type.
- Every leaf must include a source_span quoting the guideline text it came from and a
  parse_confidence in [0,1].
"""


def compile_guideline(text: str, llm: LLM) -> CriteriaTree:
    user = f"GUIDELINE TEXT:\n{text}\n\nReturn the criteria tree JSON."
    raw = llm.complete_json(COMPILER_SYSTEM, user)
    return CriteriaTree.model_validate(raw)


def compile_cached(data: bytes, llm: LLM) -> CriteriaTree:
    h = store.content_hash(data)
    cached = store.load_tree(h)
    if cached is not None:
        return cached
    tree = compile_guideline(extract_text(data), llm)
    store.save_tree(h, tree)
    return tree
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest backend/tests/test_compiler.py -v`
Expected: PASS (1 test)

- [ ] **Step 6: Commit**

```bash
git add backend/app/store.py backend/app/compiler.py backend/tests/test_compiler.py
git commit -m "feat: add guideline compiler with closed-vocabulary prompt and disk cache"
```

---

### Task 7: Router — order extraction + branch selection

**Files:**
- Create: `backend/app/router.py`, `backend/tests/test_router.py`

**Interfaces:**
- Consumes: `LLM`, `models.Order`, `models.CriteriaTree`, `reference.canonical_vein`.
- Produces:
  - `extract_order(chart_text: str, llm: LLM) -> Order`
  - `select_branch(order: Order, tree: CriteriaTree) -> tuple[list[CriteriaBranch], str | None]` — returns (branches to evaluate, flag). Single confident match → one branch, no flag. Zero/multiple → all branches + `"ambiguous_route"`.

- [ ] **Step 1: Write the failing test** — `backend/tests/test_router.py`

```python
from app.llm import FakeLLM
from app.models import Order, CriteriaTree
from app.router import extract_order, select_branch

TREE = CriteriaTree.model_validate({
    "guideline_id": "g", "title": "t", "branches": [
        {"branch_id": "saphenous", "vein_types": ["great_saphenous", "small_saphenous"],
         "procedure_label": "saph", "root": {"kind": "leaf", "id": "x", "predicate": "boolean",
         "field": "x", "threshold": True, "human_readable": "x"}},
        {"branch_id": "perforator", "vein_types": ["perforator"],
         "procedure_label": "perf", "root": {"kind": "leaf", "id": "y", "predicate": "boolean",
         "field": "y", "threshold": True, "human_readable": "y"}},
    ],
})


def test_extract_order_normalizes_vein():
    fake = FakeLLM([{"modality": "radiofrequency", "vein": "GSV",
                     "laterality": "right", "cpt": "36475", "raw": "RFA right GSV"}])
    order = extract_order("Plan: RFA of right GSV", fake)
    assert order.vein == "great_saphenous"   # normalized via canonical_vein
    assert order.modality == "radiofrequency"


def test_select_branch_single_match():
    branches, flag = select_branch(Order(vein="great_saphenous"), TREE)
    assert [b.branch_id for b in branches] == ["saphenous"]
    assert flag is None


def test_select_branch_ambiguous_falls_back_to_all():
    branches, flag = select_branch(Order(vein=None), TREE)
    assert len(branches) == 2
    assert flag == "ambiguous_route"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_router.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write `backend/app/router.py`**

```python
from .llm import LLM
from .models import Order, CriteriaTree, CriteriaBranch
from .reference import canonical_vein

ROUTER_SYSTEM = """Extract the ordered/planned procedure from a patient chart.
Return JSON: {"modality": str|null, "vein": str|null, "laterality": str|null,
"cpt": str|null, "raw": str|null}. "vein" should name the target vessel as written.
If no procedure is clearly ordered, set fields to null."""


def extract_order(chart_text: str, llm: LLM) -> Order:
    raw = llm.complete_json(ROUTER_SYSTEM, f"CHART:\n{chart_text}\n\nReturn the order JSON.")
    order = Order.model_validate(raw)
    if order.vein:
        order.vein = canonical_vein(order.vein) or order.vein
    return order


def select_branch(order: Order, tree: CriteriaTree) -> tuple[list[CriteriaBranch], str | None]:
    if order.vein:
        matches = [b for b in tree.branches if order.vein in b.vein_types]
        if len(matches) == 1:
            return matches, None
    return list(tree.branches), "ambiguous_route"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/tests/test_router.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/router.py backend/tests/test_router.py
git commit -m "feat: add router with LLM order extraction and deterministic branch selection"
```

---

### Task 8: Chart Extractor (guided extraction)

**Files:**
- Create: `backend/app/extractor.py`, `backend/tests/test_extractor.py`

**Interfaces:**
- Consumes: `LLM`, `models.Node`, `models.Fact`, `evaluator._collect_leaf_ids` pattern (re-implement a local field collector).
- Produces:
  - `required_fields(root: Node) -> list[dict]` — for each leaf, `{field, predicate, human_readable, threshold, unit}` describing what to look for.
  - `extract_facts(chart_text: str, root: Node, llm: LLM) -> dict[str, Fact]` — guided extraction returning one Fact per required field; missing → `found: false`.

- [ ] **Step 1: Write the failing test** — `backend/tests/test_extractor.py`

```python
from app.llm import FakeLLM
from app.models import AllOf, LeafNode, PredicateType
from app.extractor import required_fields, extract_facts


ROOT = AllOf(id="r", children=[
    LeafNode(id="a", predicate=PredicateType.NUMERIC_GTE, field="vein_diameter_mm",
             threshold=3, unit="mm", human_readable="Varicosities >= 3 mm"),
    LeafNode(id="b", predicate=PredicateType.BOOLEAN, field="saphenous_reflux_demonstrated",
             threshold=True, human_readable="Demonstrated reflux"),
])


def test_required_fields_lists_every_leaf():
    fields = {f["field"] for f in required_fields(ROOT)}
    assert fields == {"vein_diameter_mm", "saphenous_reflux_demonstrated"}


def test_extract_facts_maps_and_defaults_missing():
    fake = FakeLLM([{"facts": [
        {"field": "vein_diameter_mm", "value": 5, "unit": "mm", "found": True,
         "source_span": {"text": "GSV 5mm"}, "confidence": 0.9},
        # reflux omitted entirely by the model -> must become found: false
    ]}])
    facts = extract_facts("chart text", ROOT, fake)
    assert facts["vein_diameter_mm"].value == 5
    assert facts["saphenous_reflux_demonstrated"].found is False
    assert "vein_diameter_mm" in fake.calls[0]["user"]  # guided by the field list
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_extractor.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write `backend/app/extractor.py`**

```python
import json

from .llm import LLM
from .models import Node, LeafNode, UnmappableNode, Fact

EXTRACTOR_SYSTEM = """You extract clinical facts from a patient chart, but ONLY the fields requested.
For each requested field return: {"field": str, "value": <number|string|bool|null>,
"unit": str|null, "found": bool, "source_span": {"text": <verbatim quote from chart>},
"confidence": float}. If the chart does not document a field, return found=false and value=null.
Do NOT infer facts that are not supported by the chart text. Return JSON: {"facts": [ ... ]}."""


def required_fields(root: Node) -> list[dict]:
    out: list[dict] = []

    def walk(n: Node):
        if isinstance(n, LeafNode):
            out.append({"field": n.field, "predicate": n.predicate.value,
                        "human_readable": n.human_readable,
                        "threshold": n.threshold, "unit": n.unit})
        elif isinstance(n, UnmappableNode):
            return
        else:
            for c in n.children:
                walk(c)

    walk(root)
    # de-dupe by field, keep first
    seen, deduped = set(), []
    for f in out:
        if f["field"] not in seen:
            seen.add(f["field"])
            deduped.append(f)
    return deduped


def extract_facts(chart_text: str, root: Node, llm: LLM) -> dict[str, Fact]:
    fields = required_fields(root)
    user = (f"CHART:\n{chart_text}\n\nExtract these fields:\n{json.dumps(fields, indent=2)}\n"
            "Return JSON {\"facts\": [...]}.")
    raw = llm.complete_json(EXTRACTOR_SYSTEM, user)
    by_field = {f["field"]: Fact.model_validate(f) for f in raw.get("facts", [])}
    result: dict[str, Fact] = {}
    for f in fields:
        result[f["field"]] = by_field.get(f["field"], Fact(field=f["field"], found=False))
    return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/tests/test_extractor.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/extractor.py backend/tests/test_extractor.py
git commit -m "feat: add guided chart fact extractor with missing-field defaults"
```

---

### Task 9: Verifier (2nd LLM on pivotal / low-confidence leaves)

**Files:**
- Create: `backend/app/verifier.py`, `backend/tests/test_verifier.py`

**Interfaces:**
- Consumes: `LLM`, `evaluator.pivotal_leaf_ids`, `models`.
- Produces:
  - `leaves_to_verify(root, facts) -> list[str]` — pivotal leaf ids whose fact is INSUFFICIENT or `confidence < 0.75`.
  - `verify_facts(chart_text, root, facts, leaf_ids, verifier_llm) -> dict[str, Fact]` — returns updated facts; on disagreement between original and verifier, marks `Fact.confidence` low and appends a `"verifier_disagreement"` marker via a companion `flags` dict returned alongside. Signature: returns `tuple[dict[str, Fact], dict[str, str]]` (facts, per-field flag).

- [ ] **Step 1: Write the failing test** — `backend/tests/test_verifier.py`

```python
from app.llm import FakeLLM
from app.models import AllOf, LeafNode, PredicateType, Fact
from app.verifier import leaves_to_verify, verify_facts

ROOT = AllOf(id="r", children=[
    LeafNode(id="a", predicate=PredicateType.BOOLEAN, field="fa", threshold=True, human_readable="a"),
    LeafNode(id="b", predicate=PredicateType.BOOLEAN, field="fb", threshold=True, human_readable="b"),
])


def test_leaves_to_verify_picks_pivotal_insufficient():
    facts = {"fa": Fact(field="fa", value=True, found=True, confidence=0.99)}
    # fb missing -> INSUFFICIENT and pivotal (all_of) -> should be verified
    field_ids = leaves_to_verify(ROOT, facts)
    assert "b" in field_ids
    assert "a" not in field_ids


def test_verify_flags_disagreement():
    facts = {
        "fa": Fact(field="fa", value=True, found=True, confidence=0.99),
        "fb": Fact(field="fb", value=None, found=False, confidence=0.2),
    }
    # verifier now claims fb IS found true
    verifier = FakeLLM([{"facts": [
        {"field": "fb", "value": True, "found": True, "source_span": {"text": "reflux noted"},
         "confidence": 0.8}]}])
    updated, flags = verify_facts("chart", ROOT, facts, ["b"], verifier)
    assert flags["fb"] == "verifier_disagreement"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_verifier.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write `backend/app/verifier.py`**

```python
from .llm import LLM
from .models import Node, LeafNode, UnmappableNode, Fact
from .evaluator import pivotal_leaf_ids
from .extractor import EXTRACTOR_SYSTEM


def _leaf_by_id(root: Node) -> dict[str, LeafNode]:
    out: dict[str, LeafNode] = {}

    def walk(n: Node):
        if isinstance(n, LeafNode):
            out[n.id] = n
        elif not isinstance(n, UnmappableNode):
            for c in n.children:
                walk(c)

    walk(root)
    return out


def leaves_to_verify(root: Node, facts: dict[str, Fact]) -> list[str]:
    pivotal = set(pivotal_leaf_ids(root, facts))
    leaves = _leaf_by_id(root)
    out = []
    for lid in pivotal:
        leaf = leaves.get(lid)
        if leaf is None:
            continue
        f = facts.get(leaf.field)
        if f is None or not f.found or f.confidence < 0.75:
            out.append(lid)
    return out


def verify_facts(chart_text: str, root: Node, facts: dict[str, Fact],
                 leaf_ids: list[str], verifier: LLM) -> tuple[dict[str, Fact], dict[str, str]]:
    leaves = _leaf_by_id(root)
    fields = []
    for lid in leaf_ids:
        leaf = leaves.get(lid)
        if leaf:
            fields.append({"field": leaf.field, "predicate": leaf.predicate.value,
                           "human_readable": leaf.human_readable, "threshold": leaf.threshold})
    if not fields:
        return facts, {}
    import json
    user = (f"CHART:\n{chart_text}\n\nIndependently determine these fields:\n"
            f"{json.dumps(fields, indent=2)}\nReturn JSON {{\"facts\": [...]}}.")
    raw = verifier.complete_json(EXTRACTOR_SYSTEM, user)
    v_by_field = {f["field"]: Fact.model_validate(f) for f in raw.get("facts", [])}

    updated = dict(facts)
    flags: dict[str, str] = {}
    for f in fields:
        field = f["field"]
        orig = facts.get(field)
        vf = v_by_field.get(field)
        if vf is None:
            continue
        orig_found = bool(orig and orig.found)
        orig_val = orig.value if orig else None
        if vf.found != orig_found or vf.value != orig_val:
            flags[field] = "verifier_disagreement"
            # keep original value but drop confidence to force human review
            if orig:
                orig.confidence = min(orig.confidence, 0.3)
        else:
            # agreement -> boost confidence
            if orig:
                orig.confidence = max(orig.confidence, 0.9)
    return updated, flags
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/tests/test_verifier.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/verifier.py backend/tests/test_verifier.py
git commit -m "feat: add second-model verifier for pivotal low-confidence leaves"
```

---

### Task 10: Pipeline orchestration

**Files:**
- Create: `backend/app/pipeline.py`, `backend/tests/test_pipeline.py`

**Interfaces:**
- Consumes: all prior modules.
- Produces:
  - `RunResult` model: `{guideline_id, order, evaluated_branches: [BranchResult], route_flag}` where `BranchResult = {branch_id, procedure_label, verdict: Status, tree: EvalResult, gap_flags: dict}`.
  - `run(guideline_bytes: bytes, chart_bytes: bytes, primary: LLM, verifier: LLM) -> RunResult`.

- [ ] **Step 1: Write the failing test** — `backend/tests/test_pipeline.py`

```python
from app.llm import FakeLLM
from app.models import Status
from app.pipeline import run
from app.pdf_extract import extract_text
from pathlib import Path
import pytest

SAMPLES = Path(__file__).parent / "samples"

# Compiled tree the primary LLM will "return" for the guideline.
TREE_JSON = {
    "guideline_id": "02-33000-31", "title": "Varicose Veins", "branches": [{
        "branch_id": "saphenous", "vein_types": ["great_saphenous"], "procedure_label": "saph",
        "root": {"kind": "all_of", "id": "root", "children": [
            {"kind": "leaf", "id": "reflux", "predicate": "boolean",
             "field": "saphenous_reflux_demonstrated", "threshold": True, "human_readable": "reflux"},
            {"kind": "leaf", "id": "size", "predicate": "numeric_gte", "field": "vein_diameter_mm",
             "threshold": 3, "unit": "mm", "human_readable": "size"},
        ]}}]}
ORDER_JSON = {"modality": "radiofrequency", "vein": "great_saphenous", "laterality": "right",
              "cpt": "36475", "raw": "RFA right GSV"}
FACTS_JSON = {"facts": [
    {"field": "saphenous_reflux_demonstrated", "value": True, "found": True,
     "source_span": {"text": "reflux present"}, "confidence": 0.95},
    {"field": "vein_diameter_mm", "value": 5, "unit": "mm", "found": True,
     "source_span": {"text": "5 mm"}, "confidence": 0.95},
]}


def test_run_end_to_end_with_fakes(tmp_path, monkeypatch):
    monkeypatch.setenv("CACHE_DIR", str(tmp_path))
    import importlib, app.store
    importlib.reload(app.store)
    primary = FakeLLM([TREE_JSON, ORDER_JSON, FACTS_JSON])
    verifier = FakeLLM([])  # nothing pivotal+low-conf expected (all high-conf MET)
    result = run(b"guideline-bytes", b"chart-bytes", primary, verifier)
    br = result.evaluated_branches[0]
    assert br.verdict == Status.MET
    assert result.order.vein == "great_saphenous"
```

Note: because `run` calls `extract_text` on the raw bytes, in the test pass real small PDFs OR monkeypatch `extract_text`. Simplest: monkeypatch `app.pipeline.extract_text` to return a fixed string. Adjust the test to:

```python
def test_run_end_to_end_with_fakes(tmp_path, monkeypatch):
    monkeypatch.setenv("CACHE_DIR", str(tmp_path))
    import app.store, importlib
    importlib.reload(app.store)
    import app.compiler, app.pipeline
    importlib.reload(app.compiler); importlib.reload(app.pipeline)
    monkeypatch.setattr(app.pipeline, "extract_text", lambda b: "text")
    monkeypatch.setattr(app.compiler, "extract_text", lambda b: "text")
    primary = FakeLLM([TREE_JSON, ORDER_JSON, FACTS_JSON])
    verifier = FakeLLM([])
    result = app.pipeline.run(b"g", b"c", primary, verifier)
    assert result.evaluated_branches[0].verdict == Status.MET
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_pipeline.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write `backend/app/pipeline.py`**

```python
from pydantic import BaseModel

from .llm import LLM
from .models import Status, Order, EvalResult
from .pdf_extract import extract_text
from .compiler import compile_cached
from .router import extract_order, select_branch
from .extractor import extract_facts
from .verifier import leaves_to_verify, verify_facts
from .evaluator import evaluate


class BranchResult(BaseModel):
    branch_id: str
    procedure_label: str
    verdict: Status
    tree: EvalResult
    gap_flags: dict[str, str] = {}


class RunResult(BaseModel):
    guideline_id: str
    title: str
    order: Order
    route_flag: str | None = None
    evaluated_branches: list[BranchResult]


def run(guideline_bytes: bytes, chart_bytes: bytes, primary: LLM, verifier: LLM) -> RunResult:
    tree = compile_cached(guideline_bytes, primary)
    chart_text = extract_text(chart_bytes)
    order = extract_order(chart_text, primary)
    branches, route_flag = select_branch(order, tree)

    results: list[BranchResult] = []
    for branch in branches:
        facts = extract_facts(chart_text, branch.root, primary)
        to_verify = leaves_to_verify(branch.root, facts)
        gap_flags: dict[str, str] = {}
        if to_verify:
            facts, gap_flags = verify_facts(chart_text, branch.root, facts, to_verify, verifier)
        eval_tree = evaluate(branch.root, facts)
        results.append(BranchResult(
            branch_id=branch.branch_id, procedure_label=branch.procedure_label,
            verdict=eval_tree.status, tree=eval_tree, gap_flags=gap_flags,
        ))

    return RunResult(guideline_id=tree.guideline_id, title=tree.title, order=order,
                     route_flag=route_flag, evaluated_branches=results)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/tests/test_pipeline.py -v`
Expected: PASS

- [ ] **Step 5: Run the whole suite**

Run: `pytest -v`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add backend/app/pipeline.py backend/tests/test_pipeline.py
git commit -m "feat: add end-to-end pipeline orchestration"
```

---

### Task 11: FastAPI endpoints

**Files:**
- Create: `backend/app/main.py`, `backend/tests/test_api.py`

**Interfaces:**
- Produces:
  - `POST /api/evaluate` (multipart: `guideline` file, `chart` file) → `RunResult` JSON. Uses `openai_client()` primary + `mistral_client()` verifier by default; both overridable via app state for tests.
  - `GET /api/health` → `{"status": "ok"}`.
  - Serves the built frontend from `/` if `frontend/dist` exists.

- [ ] **Step 1: Write the failing test** — `backend/tests/test_api.py`

```python
from fastapi.testclient import TestClient
from app.main import app, get_clients
from app.llm import FakeLLM

TREE_JSON = {"guideline_id": "g", "title": "t", "branches": [{
    "branch_id": "saphenous", "vein_types": ["great_saphenous"], "procedure_label": "saph",
    "root": {"kind": "leaf", "id": "reflux", "predicate": "boolean",
             "field": "saphenous_reflux_demonstrated", "threshold": True, "human_readable": "reflux"}}]}
ORDER_JSON = {"modality": "rfa", "vein": "great_saphenous", "laterality": "right", "cpt": "36475", "raw": "x"}
FACTS_JSON = {"facts": [{"field": "saphenous_reflux_demonstrated", "value": True, "found": True,
                         "source_span": {"text": "reflux"}, "confidence": 0.95}]}


def test_health():
    assert TestClient(app).get("/api/health").json() == {"status": "ok"}


def test_evaluate(monkeypatch, tmp_path):
    monkeypatch.setenv("CACHE_DIR", str(tmp_path))
    import importlib, app.store, app.compiler, app.pipeline
    importlib.reload(app.store); importlib.reload(app.compiler); importlib.reload(app.pipeline)
    monkeypatch.setattr(app.pipeline, "extract_text", lambda b: "text")
    monkeypatch.setattr(app.compiler, "extract_text", lambda b: "text")
    app.dependency_overrides[get_clients] = lambda: (
        FakeLLM([TREE_JSON, ORDER_JSON, FACTS_JSON]), FakeLLM([]))
    client = TestClient(app)
    resp = client.post("/api/evaluate",
                       files={"guideline": ("g.pdf", b"g", "application/pdf"),
                              "chart": ("c.pdf", b"c", "application/pdf")})
    assert resp.status_code == 200
    assert resp.json()["evaluated_branches"][0]["verdict"] == "MET"
    app.dependency_overrides.clear()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_api.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write `backend/app/main.py`**

```python
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, Depends
from fastapi.staticfiles import StaticFiles

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
    return run(guideline_bytes, chart_bytes, primary, verifier)


_dist = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
if _dist.exists():
    app.mount("/", StaticFiles(directory=str(_dist), html=True), name="frontend")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/tests/test_api.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/main.py backend/tests/test_api.py
git commit -m "feat: add FastAPI evaluate + health endpoints"
```

---

### Task 12: Frontend SPA

**Files:**
- Create: `frontend/package.json`, `frontend/vite.config.ts`, `frontend/tsconfig.json`, `frontend/index.html`, `frontend/src/main.tsx`, `frontend/src/App.tsx`, `frontend/src/api.ts`, `frontend/src/components/GapList.tsx`

**Interfaces:**
- Consumes: `POST /api/evaluate`.
- Produces: a single page — two file inputs (guideline, chart), a Submit button, and a rendered gap list grouping criteria by status with color coding (MET green, NOT_MET red, INSUFFICIENT amber), showing guideline citation and chart evidence per leaf, plus route/verifier flags.

This task is verified manually (no unit test). Keep it minimal.

- [ ] **Step 1: Write `frontend/package.json`**

```json
{
  "name": "aira-frontend",
  "private": true,
  "type": "module",
  "scripts": { "dev": "vite", "build": "vite build", "preview": "vite preview" },
  "dependencies": { "react": "^18.3.1", "react-dom": "^18.3.1" },
  "devDependencies": {
    "@vitejs/plugin-react": "^4.3.1", "typescript": "^5.5.0", "vite": "^5.4.0",
    "@types/react": "^18.3.0", "@types/react-dom": "^18.3.0"
  }
}
```

- [ ] **Step 2: Write `frontend/vite.config.ts`**

```typescript
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/api": "http://localhost:8000" } },
});
```

- [ ] **Step 3: Write `frontend/tsconfig.json`**

```json
{
  "compilerOptions": {
    "target": "ES2020", "useDefineForClassFields": true, "lib": ["ES2020", "DOM", "DOM.Iterable"],
    "module": "ESNext", "skipLibCheck": true, "moduleResolution": "bundler",
    "jsx": "react-jsx", "strict": true, "noEmit": true
  },
  "include": ["src"]
}
```

- [ ] **Step 4: Write `frontend/index.html`**

```html
<!doctype html>
<html>
  <head><meta charset="UTF-8" /><title>Medical Necessity Checker</title></head>
  <body><div id="root"></div><script type="module" src="/src/main.tsx"></script></body>
</html>
```

- [ ] **Step 5: Write `frontend/src/main.tsx`**

```tsx
import React from "react";
import ReactDOM from "react-dom/client";
import { App } from "./App";

ReactDOM.createRoot(document.getElementById("root")!).render(<App />);
```

- [ ] **Step 6: Write `frontend/src/api.ts`**

```typescript
export type Status = "MET" | "NOT_MET" | "INSUFFICIENT_EVIDENCE";

export interface EvalNode {
  node_id: string; kind: string; status: Status; human_readable?: string;
  field?: string; evidence?: { value?: unknown; found: boolean; source_span?: { text: string } };
  guideline_span?: { text: string }; flags: string[]; children: EvalNode[];
}
export interface BranchResult {
  branch_id: string; procedure_label: string; verdict: Status;
  tree: EvalNode; gap_flags: Record<string, string>;
}
export interface RunResult {
  guideline_id: string; title: string;
  order: { modality?: string; vein?: string; laterality?: string; cpt?: string };
  route_flag?: string | null; evaluated_branches: BranchResult[];
}

export async function evaluate(guideline: File, chart: File): Promise<RunResult> {
  const fd = new FormData();
  fd.append("guideline", guideline);
  fd.append("chart", chart);
  const resp = await fetch("/api/evaluate", { method: "POST", body: fd });
  if (!resp.ok) throw new Error(`evaluate failed: ${resp.status}`);
  return resp.json();
}
```

- [ ] **Step 7: Write `frontend/src/components/GapList.tsx`**

```tsx
import type { EvalNode, Status } from "../api";

const COLOR: Record<Status, string> = {
  MET: "#137333", NOT_MET: "#b3261e", INSUFFICIENT_EVIDENCE: "#a56300",
};
const LABEL: Record<Status, string> = {
  MET: "Met", NOT_MET: "Not met", INSUFFICIENT_EVIDENCE: "Missing evidence",
};

function leaves(node: EvalNode): EvalNode[] {
  if (node.kind === "leaf" || node.kind === "unmappable") return [node];
  return node.children.flatMap(leaves);
}

export function GapList({ tree }: { tree: EvalNode }) {
  return (
    <ul style={{ listStyle: "none", padding: 0 }}>
      {leaves(tree).map((n) => (
        <li key={n.node_id} style={{ borderLeft: `4px solid ${COLOR[n.status]}`,
             padding: "8px 12px", margin: "8px 0", background: "#fafafa" }}>
          <strong style={{ color: COLOR[n.status] }}>{LABEL[n.status]}</strong> — {n.human_readable}
          {n.guideline_span && <div style={{ fontSize: 12, color: "#555" }}>
            Guideline: “{n.guideline_span.text}”</div>}
          <div style={{ fontSize: 12, color: "#555" }}>
            {n.evidence?.found
              ? <>Chart: “{n.evidence.source_span?.text}”</>
              : <em>NOT FOUND IN CHART</em>}
          </div>
          {n.flags.length > 0 && <div style={{ fontSize: 12, color: "#a56300" }}>
            ⚑ {n.flags.join(", ")}</div>}
        </li>
      ))}
    </ul>
  );
}
```

- [ ] **Step 8: Write `frontend/src/App.tsx`**

```tsx
import { useState } from "react";
import { evaluate, type RunResult, type Status } from "./api";
import { GapList } from "./components/GapList";

const VERDICT_TEXT: Record<Status, string> = {
  MET: "MEETS medical necessity", NOT_MET: "DOES NOT MEET",
  INSUFFICIENT_EVIDENCE: "INCOMPLETE — items to resolve",
};

export function App() {
  const [guideline, setGuideline] = useState<File | null>(null);
  const [chart, setChart] = useState<File | null>(null);
  const [result, setResult] = useState<RunResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    if (!guideline || !chart) return;
    setLoading(true); setError(null); setResult(null);
    try { setResult(await evaluate(guideline, chart)); }
    catch (e) { setError(String(e)); }
    finally { setLoading(false); }
  }

  return (
    <div style={{ maxWidth: 780, margin: "40px auto", fontFamily: "system-ui" }}>
      <h1>Medical Necessity Checker</h1>
      <div style={{ display: "flex", gap: 16, alignItems: "center" }}>
        <label>Guideline PDF <input type="file" accept="application/pdf"
          onChange={(e) => setGuideline(e.target.files?.[0] ?? null)} /></label>
        <label>Patient chart PDF <input type="file" accept="application/pdf"
          onChange={(e) => setChart(e.target.files?.[0] ?? null)} /></label>
        <button onClick={submit} disabled={!guideline || !chart || loading}>
          {loading ? "Evaluating…" : "Evaluate"}</button>
      </div>
      {error && <p style={{ color: "#b3261e" }}>{error}</p>}
      {result && (
        <div style={{ marginTop: 24 }}>
          <p><strong>Order:</strong> {result.order.modality} of {result.order.vein}
            {result.route_flag && <span style={{ color: "#a56300" }}> ⚑ {result.route_flag}</span>}</p>
          {result.evaluated_branches.map((b) => (
            <div key={b.branch_id} style={{ marginBottom: 24 }}>
              <h2 style={{ marginBottom: 4 }}>{b.procedure_label}</h2>
              <p style={{ fontWeight: 700 }}>{VERDICT_TEXT[b.verdict]}</p>
              <GapList tree={b.tree} />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 9: Build to verify it compiles**

Run: `cd frontend && npm install && npm run build`
Expected: `dist/` produced with no TypeScript errors.

- [ ] **Step 10: Commit**

```bash
git add frontend
git commit -m "feat: add React SPA with gap-list UI"
```

---

### Task 13: Dockerize + one-line run + README

**Files:**
- Create: `Dockerfile`, `docker-compose.yml`, `.env.example`, `.dockerignore`, `README.md`

**Interfaces:**
- Produces: `docker compose up` builds the frontend, serves API + static UI on `http://localhost:8000`.

- [ ] **Step 1: Write `.env.example`**

```
OPENAI_API_KEY=sk-...
MISTRAL_API_KEY=...
PRIMARY_MODEL=gpt-4o
VERIFIER_MODEL=mistral-large-latest
CACHE_DIR=/data/guidelines
```

- [ ] **Step 2: Write `Dockerfile` (multi-stage: build frontend, run backend)**

```dockerfile
# --- frontend build ---
FROM node:20-slim AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install
COPY frontend/ ./
RUN npm run build

# --- backend runtime ---
FROM python:3.11-slim
WORKDIR /app
COPY pyproject.toml ./
RUN pip install --no-cache-dir .
COPY backend/ ./backend/
COPY --from=frontend /frontend/dist ./frontend/dist
ENV CACHE_DIR=/data/guidelines
VOLUME ["/data"]
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--app-dir", "backend", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 3: Write `docker-compose.yml`**

```yaml
services:
  app:
    build: .
    ports: ["8000:8000"]
    env_file: [.env]
    volumes: ["guideline-cache:/data"]
volumes:
  guideline-cache:
```

- [ ] **Step 4: Write `.dockerignore`**

```
**/node_modules
**/__pycache__
**/dist
.git
.env
```

- [ ] **Step 5: Write `README.md`**

````markdown
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

See `docs/superpowers/specs/2026-07-15-medical-necessity-checker-design.md`. In short: the LLM
compiles the guideline into a criteria tree (data) and extracts patient facts from the chart (data);
a pure-Python three-valued evaluator (code) produces the verdict. A second model re-verifies only
the leaves the verdict actually hinges on.

## Tests

```bash
pip install -e ".[dev]" && pytest
```
````

- [ ] **Step 6: Verify one-line run on a clean state**

```bash
cp .env.example .env   # fill in real keys before running for real
docker compose up --build
# in another shell:
curl -s localhost:8000/api/health   # expect {"status":"ok"}
```
Expected: health returns ok; browser shows the UI.

- [ ] **Step 7: Commit**

```bash
git add Dockerfile docker-compose.yml .env.example .dockerignore README.md
git commit -m "feat: dockerize with one-line docker compose run and README"
```

---

## Self-Review

**Spec coverage:**
- Pipeline (spec §Pipeline) → Task 10. ✓
- Criteria tree closed vocabulary (spec §Criteria Tree) → Tasks 1, 6. ✓
- Three-valued Kleene evaluator (spec §Three-valued) → Task 3. ✓
- Guided extraction (spec §Chart Extractor) → Task 8. ✓
- Router with anatomy-based branch selection + fallback (spec §Router) → Task 7. ✓
- Verifier on pivotal/low-confidence leaves (spec §Verifier) → Task 9. ✓
- Reference data: CEAP ordinal + normalization (spec §reference) → Task 2. ✓
- Disk cache by content hash, no Postgres (spec §Stack) → Task 6. ✓
- Gap-list output with citations both directions (spec §Output) → Tasks 11, 12. ✓
- One-line `docker compose up`, `.env` keys (spec §Stack & run) → Task 13. ✓
- `unmappable` node as "what breaks first" (spec §What breaks first) → Tasks 1, 3, 6 (evaluator returns INSUFFICIENT + flag). ✓
- Tests: evaluator backbone + golden pipeline (spec §Testing) → Tasks 3, 10. ✓

**Placeholder scan:** No TBD/TODO; the one messy `store.py` import in Task 6 Step 3 is immediately followed by the corrected final file. All code steps contain complete code.

**Type consistency:** `Status.INSUFFICIENT` used consistently; `evaluate(node, facts, overrides)` signature consistent across evaluator/verifier/pipeline; `Fact`/`EvalResult`/`RunResult`/`BranchResult` field names consistent between backend producers and the TypeScript `api.ts` consumer (`evaluated_branches`, `gap_flags`, `route_flag`, `source_span.text`, `human_readable`).

## Notes for the implementer

- The LLM prompts (compiler, router, extractor) will need light tuning against the real BCBS FL
  PDF during execution — the tests mock the LLM, so they stay green regardless. Budget a pass to
  run the real `docker compose up` against the sample guideline + `robert_mitchell_chart_final.pdf`
  and eyeball the tree and gap list.
- If `robert_mitchell_chart_final.pdf` is available, add it as `backend/tests/samples/chart.pdf` and
  write one non-mocked golden test behind a `RUN_LIVE` env guard.
