# Medical Necessity Checker — Design

**Date:** 2026-07-15
**Context:** Aira Forward Deployed Engineer build case. A prior-authorization medical-necessity
checker for a vascular surgery practice.

## Problem

Before an insurer pays for a procedure, staff must prove *medical necessity* by showing the
patient's chart meets the insurer's published guideline criteria. Staff mostly work from tribal
knowledge, infer what's missing, and fill gaps before submitting. When something is missed, the
claim is denied.

Build a working MVP that takes a **payer guideline PDF** and a **patient chart PDF** and tells staff:
does this patient meet criteria for the ordered procedure, and **if not, exactly what is missing** —
so they can fix gaps before submitting.

**Hard constraint that drives every decision:** the evaluators will feed the product *guidelines and
charts it has never seen*. Nothing about varicose veins may be hardcoded. The example guideline is
BCBS FL "Treatments for Varicose Veins/Venous Insufficiency (02-33000-31)"; it is an example, not a
boundary.

## Core thesis: where the judgment lives

**No LLM makes the medical-necessity decision.** A deterministic rule engine does. LLMs are confined
to bounded *extraction and normalization* at two boundaries. This is the answer to the design note's
"what is data vs what is code."

| Layer | Artifact | Data or Code | Producer |
|---|---|---|---|
| Criteria tree | Guideline's rules as an AND/OR/N-of tree of atomic predicates | **DATA** (per guideline) | LLM compiles PDF → tree |
| Patient facts | Atomic clinical findings, each with citation + confidence | **DATA** (per chart) | LLM extracts chart → facts |
| Evaluator | Walks tree, matches predicates to facts, returns verdict + gaps | **CODE** (guideline-agnostic) | Pure Python |
| Reference data | CEAP ordinal ordering, unit/synonym maps | **DATA** | Authored once, in repo |

Same tree + same facts → same verdict, every time, with a full trace.

## Pipeline

One "run" = one chart evaluated against one guideline.

```
Guideline PDF ─(once per guideline, cached by content hash)─► [Compiler: LLM] ─► Criteria Tree (JSON on disk)
                                                                                     │
Patient Chart PDF ─► [Router: LLM extracts order] ─► {modality, vein, laterality, CPT?}
                                                                                     │  code selects branch
                                                                                     ▼
                                         [Chart Extractor: LLM, guided by branch predicates] ─► Patient Facts
                                                                                     │
                                         [Evaluator: PURE CODE] ─► Verdict + Gap List
                                                                                     │
                                         [Verifier: 2nd LLM] re-checks only low-confidence / verdict-pivotal leaves
```

## Components

Six isolated, independently testable units plus the web shell. Each has one purpose, a defined
interface, and can be tested in isolation.

### 1. PDF → text (code)
`pypdf` (already validated against both sample PDFs). Pure utility, shared by guideline and chart
paths. Returns text with coarse page/offset spans for citation.

### 2. Guideline Compiler (LLM — OpenAI primary)
Guideline text → **Criteria Tree** JSON. Runs **once per guideline**, cached on disk keyed by content
hash, so repeated patient runs are deterministic and cheap. Auto-parse with **confidence flags**
(no mandatory human edit step): each node carries a `parse_confidence` and a guideline `source_span`;
verdicts resting on low-confidence nodes are surfaced for review rather than silently trusted.

### 3. Router (LLM extract + code map)
LLM identifies the **ordered procedure** from the chart → `{modality, vein, laterality, CPT?}`.
**Code** maps target vein → criteria branch (the guideline branches on *anatomy*: great/small
saphenous vs accessory vs tributary vs perforator; CPT codes are *modality* codes that span vein
types, so CPT alone cannot select a branch). If the order is ambiguous or absent, **fall back to
evaluating all branches and flag it** (messy charts are an explicit test vector).

### 4. Chart Extractor (LLM — guided extraction)
Given the selected branch's predicates, extract **only the facts those predicates need** — not a
free-form chart summary. Each fact: `{field, value, unit?, source_span, confidence, found: bool}`.
Guided extraction keeps the LLM on-task and makes `found: false` a first-class signal.

### 5. Evaluator (PURE CODE — the heart)
Deterministic, guideline-agnostic three-valued engine. See below. This is where TDD lives: pure
functions, synthetic trees + facts, zero LLM.

### 6. Verifier (2nd LLM — Mistral)
For leaves that are **low-confidence** *or* **verdict-pivotal** (flipping the leaf flips the overall
outcome), the second model independently re-extracts that single item. Agreement → high confidence;
disagreement → flag for human. Targeted, so it stays cheap. This is how two API keys become a real
reliability signal instead of an arbitrary split.

### 7. Web shell (FastAPI + React/Vite)
Upload or select a guideline, upload a chart, render the gap list. Thin.

## The Criteria Tree schema

Node types:
- `all_of` — AND
- `any_of` — OR
- `n_of(k)` — at least *k* of children (handles "one or more of the following indications")
- `leaf` — an atomic predicate

**Leaf predicates use a closed vocabulary the code understands.** This closed set is the hard
code/LLM boundary.

| Predicate type | Example |
|---|---|
| `boolean` | `saphenous_reflux_demonstrated == true` |
| `numeric_gte` / `numeric_lte` | `vein_diameter_mm >= 3` |
| `ordinal_gte` | `ceap_class >= C2` (code owns the C0<C1<C2<C2r<C3<C4a<… ordering) |
| `duration_gte` | `conservative_therapy_months >= 3` (computed from dated notes) |
| `existence` | `venous_ulcer documented` |
| `negation` (wrapper) | `NOT (insufficiency secondary to DVT)` |

The LLM must express any guideline's rule using only this vocabulary. If a rule will not fit (a novel
modality, a cross-branch conditional), the compiler emits an **`unmappable` node with a flag** — it
must not invent a predicate. That flagged node is the honest, visible answer to "what breaks first
under a guideline change."

Each leaf: `{id, predicate_type, field, operator, threshold, unit?, source_span, parse_confidence,
human_readable}`.

## Patient Facts schema

`{field, value, unit?, source_span, extraction_confidence, found: bool}`. Fields align to leaf
`field`s. `found: false` drives `INSUFFICIENT_EVIDENCE`.

## Three-valued evaluation (Kleene logic)

States: `MET` / `NOT_MET` / `INSUFFICIENT_EVIDENCE`.

- **Leaf:** fact found & satisfies predicate → `MET`; found & fails → `NOT_MET`; not found → `INSUFFICIENT`.
- **all_of:** any `NOT_MET` → NOT_MET; else any `INSUFFICIENT` → INSUFFICIENT; else MET.
- **any_of:** any `MET` → MET; else any `INSUFFICIENT` → INSUFFICIENT; else NOT_MET.
- **n_of(k):** `MET` count ≥ k → MET; if (`MET` + `INSUFFICIENT`) < k → NOT_MET (unreachable); else INSUFFICIENT.

The `INSUFFICIENT` vs `NOT_MET` distinction is the denial-reduction engine:
- `INSUFFICIENT` = evidence likely exists, staff didn't attach it → **fixable, go get it**.
- `NOT_MET` = patient genuinely fails the criterion → **don't submit yet**.

## Output — the gap list (the actual product)

For the ordered procedure: **`MEETS` / `DOES NOT MEET` / `INCOMPLETE — N items to resolve`**, then per
criterion:
- status · plain-English text · **guideline citation** · **chart evidence** (quote + location) *or*
  `NOT FOUND IN CHART` · confidence / verifier flag.
- Action summary, e.g. "To submit: attach the duplex reflux study; document ≥3 months compression therapy."

## What breaks first (design note)

1. A guideline rule outside the predicate vocabulary → `unmappable` flag (visible, not silently dropped).
2. Evidence present but oddly phrased → extractor misses it → lands as `INSUFFICIENT` (safe: staff
   re-check) rather than a wrong `MET`.
3. Vague/absent order → route-to-all-branches + flag.
4. Unit/ordinal edge cases (`"3–4 mm"`, `"C2–C3"`) → explicit normalization rules in the reference layer.

## Stack & run

- **Backend:** Python + FastAPI · `pypdf` · `openai` + `mistralai` SDKs.
- **Persistence:** guideline trees cached as JSON files on disk keyed by content hash. **No Postgres.**
- **Frontend:** small React/Vite SPA.
- **Run:** `docker compose up` — serves UI + API; API keys via `.env`. One line, clean checkout.
- **Config:** LLM provider/model swappable via env; primary = OpenAI, verifier = Mistral.

## Testing

- Evaluator: unit tests, pure and deterministic — synthetic trees × synthetic facts covering every
  node type and every Kleene combination. This is the correctness backbone.
- Router branch-selection: unit tests over `{vein → branch}` mapping incl. ambiguous fallback.
- Golden runs: the provided `robert_mitchell_chart_final` chart + a few synthetic patients (a clean
  MEET, a clear NOT_MET, an INSUFFICIENT-only) against the BCBS FL tree.

## Out of scope (protecting the half-day budget)

- HIPAA/PHI, security, infra (explicitly excluded by the brief).
- Postgres / run-history persistence.
- Human tree-editing UI (auto-parse + flags instead).
- Multi-guideline reconciliation, appeals drafting, EHR integration.
