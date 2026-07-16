# Design Note — Medical Necessity Checker

*The build-case ask: where the judgment lives (what is data, what is code), and what breaks
first under a guideline change or a messy chart.*

## Where the judgment lives

**No LLM makes the medical-necessity decision.** The decision is made by a deterministic,
guideline-agnostic rule engine ([evaluator.py](backend/app/evaluator.py)) walking a structured
criteria tree against structured patient facts. LLMs are confined to two bounded
extraction jobs, and everything they produce is data that the code judges:

| Artifact | Data or Code | Produced by | Lives in |
|---|---|---|---|
| **Criteria tree** — the guideline's rules as an AND/OR/N-of tree of atomic predicates | Data (per guideline, cached on disk) | GPT-4o, once per guideline+prompt version | [compiler.py](backend/app/compiler.py) |
| **Patient facts** — atomic findings, each with a chart quote and confidence | Data (per chart) | GPT-4o, guided by the selected branch's predicates | [extractor.py](backend/app/extractor.py) |
| **The verdict** — three-valued Kleene evaluation, gap list, pivotality | **Code** (pure, deterministic, no LLM) | — | [evaluator.py](backend/app/evaluator.py) |
| Branch routing (which procedure's criteria apply) | Code over an LLM-extracted order | order: GPT-4o; selection: code | [router.py](backend/app/router.py) |
| Cross-model verification of shaky, verdict-swinging facts | Code decides *when*; Mistral re-extracts | [verifier.py](backend/app/verifier.py) |
| CEAP ordering, vein synonyms, measurement normalization | Data (authored, in repo) | — | [reference.py](backend/app/reference.py) |

The hard boundary is a **closed predicate vocabulary** (`boolean`, `numeric_gte/lte`,
`ordinal_gte`, `duration_gte`, `existence`, plus a `negated` wrapper). The compiler must
express any guideline using only these; when it can't, it must emit an explicit
`unmappable` node rather than invent semantics. Against the real BCBS FL policy, the
"experimental/investigational" tributary techniques and cosmetic telangiectasia sections
correctly compiled to flagged `unmappable` nodes, not hallucinated criteria.

Three verdict states, not two: `MET`, `NOT_MET`, and `INSUFFICIENT_EVIDENCE`. The
distinction is the product: *insufficient* means "the evidence probably exists — go attach
the duplex report" (fixable before submission); *not met* means "the patient genuinely
fails this criterion — don't submit yet." Every leaf carries a guideline quote and a chart
quote (or `NOT FOUND IN CHART`), so every line of the gap list is traceable in both
directions.

The two API keys are used asymmetrically on purpose: OpenAI is the primary extractor;
Mistral is an **independent verifier** invoked only on leaves that are (a) weakly
evidenced (missing, or confidence < 0.75) and (b) *pivotal* — forcing them MET vs NOT_MET
changes the root verdict (computed by the engine, not guessed). Cross-model agreement
raises confidence; disagreement flags the field for human review in the UI. Deliberate
design choice: agreement boosts confidence even when both models were individually unsure —
the agreement itself is the signal.

## What breaks first under a guideline change

1. **Rules outside the predicate vocabulary.** A guideline requiring cross-visit temporal
   logic ("two ulcer recurrences within 12 months") or inter-branch conditions won't fit
   the vocabulary; the compiler emits `unmappable` and the branch evaluates
   `INSUFFICIENT` with a visible flag. Failure mode is *loud and conservative*, not a
   wrong MET.
2. **Compiler fidelity on compound sentences.** Our first live run against the real BCBS
   policy collapsed "demonstrated saphenous reflux AND CEAP ≥ C2" into a single
   CEAP-only leaf — the missing duplex report then had no leaf to fail. We fixed the
   prompt (one leaf per ANDed clause) and, importantly, made the guideline cache key
   include the compiler prompt, so prompt fixes automatically recompile cached
   guidelines. This class of bug — a rule silently under-split — is the most likely
   residual failure on an unseen guideline; the mitigation is `parse_confidence` flags
   plus the per-leaf guideline citations, which make a mis-parse auditable in the UI.
3. **Non-vascular guidelines.** Routing is anatomy-based (`vein_types` per branch) because
   this guideline branches by vessel. A knee-replacement policy would compile but route
   every chart to "ambiguous → evaluate all branches." Honest limitation of the MVP scope;
   the fix is a generic `applies_to` concept on branches.
4. **CEAP ordering is authored data.** A payer inventing a new classification system would
   need a new ordinal table in `reference.py`; unknown classes degrade to `INSUFFICIENT`,
   never a silent comparison.

## What breaks first under a messy chart

1. **Evidence present but phrased oddly** → the extractor misses it → the leaf lands
   `INSUFFICIENT` (safe direction: staff re-check a false gap; the payer never sees a
   false MET). Guided extraction — asking only for the selected branch's fields, with the
   requirement to quote the chart verbatim — is what keeps the extractor from wandering.
2. **Explicitly denied findings.** "No active or healed ulceration" must be `NOT_MET`, not
   MET-because-mentioned. Our first live run had exactly this bug (an `existence` leaf
   scored MET on `found=true, value=false`), and it silently corrupted the `n_of(1)`
   indications gate *and* starved the verifier (nothing looked pivotal). Fixed and
   regression-tested; the extractor prompt now distinguishes denied
   (`found=true, value=false`) from unaddressed (`found=false`).
3. **Vague or missing orders** → the router falls back to evaluating every branch and
   flags `ambiguous_route` rather than guessing.
4. **Malformed LLM output** (truncated JSON, wrong types, missing fields) → per-fact
   defensive parsing degrades that field to `INSUFFICIENT`; API surfaces 502 with the
   validation detail rather than mislabeling it a client error.

## Known limits (deliberate, half-day scope)

- No retry/backoff on LLM calls — a provider timeout fails the request cleanly.
- The verifier-disagreement UI path is tested with mocks but was never triggered in live
  runs (both models agreed on our synthetic charts) — the honest status of that feature.
- Guideline compile is ~20–25s cold, then cached; per-chart evaluation ~5s.
- Verdicts depend on extraction quality; every output is designed to be *checked*, not
  blindly trusted — citations both ways, confidence flags, and the MET / NOT_MET /
  INSUFFICIENT split exist so a human can audit any line in seconds.
