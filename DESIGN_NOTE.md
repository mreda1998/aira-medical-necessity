# Design Note — Medical Necessity Checker

## Architecture in one sentence

The application uses LLMs to turn an uploaded payer guideline and patient chart into structured data, then uses ordinary Python code to apply the guideline and produce the verdict.

The design is payer-agnostic: Florida Blue is the main regression pack, not a hard-coded ruleset. Cigna and Anthem policies use the same compiler and evaluator. Policy-specific criteria live in the compiled tree; the code knows only generic Boolean nodes, clinical predicates, and a small set of authored clinical references such as CEAP ordering and vein-name aliases.

## Where judgment lives

| Stage | Mechanism | Responsibility |
|---|---|---|
| Guideline compilation | OpenAI extraction | Convert policy prose into a criteria tree with citations |
| Order and chart extraction | OpenAI extraction | Return structured order fields and evidence states |
| Policy routing | Deterministic code | Check procedure, CPT, age, and structured order constraints |
| Medical-necessity verdict | Deterministic code | Evaluate the complete Boolean tree |
| Evidence verification | Mistral extraction | Re-check decisive chart evidence; never override the verdict |

This boundary is intentional: model output may affect the input data, but the final `MET`, `NOT_MET`, or `INSUFFICIENT_EVIDENCE` transition is reproducible and testable. `policy_not_applicable` is a separate routing outcome when the requested procedure does not match the uploaded policy.

## Pipeline

```text
Guideline PDF ──> policy compiler ──> validated/cached criteria tree ─┐
                                                                    ├─> router ─> pivotal check/verifier ─> evaluator ─> response
Chart PDF ──────> order + fact extraction ─> evidence states ──────┘
```

PDF text is extracted locally with page markers. The models receive text and return JSON; the application does not upload PDF files to a provider file store. For guidelines over 40 pages, a table-of-contents-aware selector trims background and reference pages only when it finds a safe boundary; otherwise it keeps the full document.

## How `AND`, `OR`, `ANY`, and `EITHER` are preserved

The compiler maps the policy's explicit wording into a recursive tree:

| Guideline wording | Tree node |
|---|---|
| all, each, and | `all_of` |
| any, either, one of, or | `any_of` |
| one or more of N | `n_of(k=1)` |
| at least K of N | `n_of(k=K)` |
| one clinical condition | `leaf` |

The compiler must preserve nesting rather than flattening prose. Schema validation rejects malformed trees and unknown node or predicate types; targeted fidelity checks retry known mistakes such as collapsed ranges, conjunctions, and absence requirements. The prompt requires a complete source quote for each leaf, and local code verifies its page when possible. The original policy text and compiled tree remain a review boundary: code cannot prove that the model never omitted a sentence.

The evaluator walks every node with three-valued logic:

- `all_of`: `MET` only if every child is `MET`; one `NOT_MET` is enough to fail; otherwise the result is `INSUFFICIENT_EVIDENCE`.
- `any_of`: `MET` if any child is `MET`; `NOT_MET` only if every child is `NOT_MET`; otherwise the result is `INSUFFICIENT_EVIDENCE`.
- `n_of(K)`: `MET` once at least `K` children are met; `NOT_MET` when even all unresolved children cannot reach `K`; otherwise the result is `INSUFFICIENT_EVIDENCE`.

No LLM interprets these operators at decision time. The same tree always produces the same result for the same extracted facts.

## Why the UI shows fewer items than the evaluator uses

The full evaluated tree is returned as `branch.tree`. The UI highlights only `decisive_findings`:

- a successful `AND` includes all required children;
- a successful `OR` includes the witness branch that satisfied it;
- a failed group includes the children that made success impossible;
- an unresolved group includes the missing or conflicting evidence that blocks a decision.

This keeps the screen readable without reducing the logic used for the verdict.

## Evidence provenance

Each extracted fact carries an evidence state and, when available, an exact quote with its locally resolved page and section. Guideline leaves carry the matching policy citation. The API and UI can therefore show both sides of a decision: the rule being applied and the patient evidence used to evaluate it.

Evidence state is explicit:

- `DOCUMENTED` or `EXPLICITLY_ABSENT` is usable evidence.
- `NOT_DOCUMENTED` means the chart does not answer the question.
- `CONFLICTING` forces an incomplete result when the conflict matters.

## What breaks first under a messy chart

The first likely failure is chart extraction, not Boolean evaluation.

| Messy-chart condition | Current behavior and risk |
|---|---|
| Important evidence is phrased indirectly or buried in a long note | It may become `NOT_DOCUMENTED`, producing an incomplete result. Page/quote provenance and decisive-leaf verification make this auditable, but human review remains necessary. |
| Notes disagree | The fact is marked `CONFLICTING`; a decisive conflict yields `INCOMPLETE_EVIDENCE` rather than a guessed answer. |
| The order is missing or ambiguous | Routing may return `policy_not_applicable` or `ambiguous_route`. A weak but unique text match can still misroute, so the extracted order and selected branch must remain visible for review. |
| The PDF is scanned, corrupt, or has poor layout | Preflight rejects unreadable text. OCR/vision is not yet implemented, so these documents fail before clinical evaluation. |
| A model call times out or returns invalid JSON | The API returns a typed stage-specific error. Automatic retry/backoff is still a production gap. |

The main safeguard is conservative uncertainty: missing, contradictory, or unmappable facts do not silently become clinical failure. They stay incomplete and are surfaced in the gap list.

## What breaks first under a new guideline

The generic tree handles new payer wording as long as it can be represented by the supported Boolean nodes and predicates. The first risks are:

- the compiler omits or mis-nests a criterion;
- the policy introduces a clinical concept, unit conversion, temporal rule, or exclusion that the predicate vocabulary cannot express;
- page selection misses a relevant section in an unusually structured long document.

Malformed unsupported nodes fail schema validation; valid but inexpressible rules become `unmappable` and evaluate to `INSUFFICIENT_EVIDENCE`. They are not coerced into a verdict. Adding a new payer normally means adding regression fixtures, not writing a payer-specific evaluator.

## Current validation and remaining production gaps

The suite contains 80 backend tests, including recursive Boolean semantics, unknown propagation, order routing, policy compilation, provenance, and API errors. Live regression cases cover Florida Blue, Cigna, and Anthem, with synthetic Florida Blue charts spanning all four user-facing outcomes.

The largest remaining gaps are OCR for scanned charts, retry/backoff, persisted run history, human approval of newly compiled policy trees, and production controls for PHI, access, retention, and audit logging.
