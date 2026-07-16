# Design Note — Medical Necessity Checker

*Where judgment lives, what is implemented today, and what is most likely to fail when a
guideline or chart changes.*

## Current design boundary

**No LLM produces the medical-necessity verdict.** LLMs are used to extract structured data at
four boundaries: policy criteria, the ordered procedure, chart facts, and an optional second-model
fact check. The verdict is produced by a deterministic, guideline-agnostic evaluator after those
extractions.

| Artifact or operation | Data or code | Produced by | Implementation |
|---|---|---|---|
| Criteria tree — policy rules represented as AND/OR/N-of nodes and atomic predicates | Data, cached per guideline PDF and compiler-prompt version | OpenAI primary model | [compiler.py](backend/app/compiler.py) |
| Ordered procedure — modality, vessel, CPT, description, and patient age | Data, per chart | OpenAI primary model | [router.py](backend/app/router.py) |
| Applicable branch selection | **Code**, deterministic scoring | — | [router.py](backend/app/router.py) |
| Patient facts — raw values/findings, evidence state, quote, and confidence | Data, per selected branch and chart | OpenAI primary model | [extractor.py](backend/app/extractor.py) |
| Medical-necessity verdict and decisive findings | **Code**, deterministic tree evaluation | — | [evaluator.py](backend/app/evaluator.py) |
| Pivotal-fact selection and independent re-extraction | Code selects; Mistral re-extracts | Mistral verifier model | [verifier.py](backend/app/verifier.py) |
| CEAP ordering, vein synonyms, and basic measurement parsing | Authored reference data/code | — | [reference.py](backend/app/reference.py) |

The important guarantee is narrower than “the entire run is deterministic”: once the criteria tree
and patient facts exist, the same inputs produce the same verdict. Cold LLM extraction can still
vary, and cached criteria trees preserve the first accepted policy extraction.

## Implemented pipeline

```text
Guideline PDF ──pypdf──> text ──OpenAI──> criteria tree ──schema/fidelity checks──> disk cache
                                                                  │
Chart PDF ──────pypdf──> text ──OpenAI──> order ──deterministic routing──> branch(es)
                                                                  │
                                      OpenAI extracts requested raw facts only
                                                                  │
                                   deterministic three-valued evaluation
                                                                  │
                          Mistral re-extracts weak, pivotal facts when needed
                                                                  │
                               verdict + decisive findings + review flags
```

PDFs are currently converted to text locally with `pypdf`. The application does **not** yet send
PDFs as OpenAI file inputs, and it uses Chat Completions JSON mode rather than strict Structured
Outputs. Migrating that input/schema boundary is the next planned step; it does not change the
deterministic evaluator boundary.

### Policy representation

The criteria tree uses structural node kinds `all_of`, `any_of`, `n_of`, `leaf`, and `unmappable`.
A discriminated Pydantic union rejects malformed node kinds before evaluation.

The closed leaf-predicate vocabulary is:

- `boolean`
- `numeric_gt`, `numeric_gte`, `numeric_lt`, `numeric_lte`
- `ordinal_gte`
- `duration_gte`
- `existence`

Negation is represented by `negated: true` on a leaf. Policy comparisons remain in the criteria
tree; they are deliberately excluded from chart-extraction requests so the LLM returns a raw value
such as `33.3`, not a policy conclusion such as `false`.

Each branch can carry applicability metadata independent of its medical-necessity criteria:
`procedure_codes`, `procedure_aliases`, `min_age`, `max_age`, and the legacy vascular
`vein_types`. Routing scores exact CPT/HCPCS and vessel matches, procedure aliases, specific label
tokens, and age bounds. A unique best match selects one branch. A tie returns the tied candidates;
no match returns all branches. Both cases carry `ambiguous_route` rather than silently guessing.

### Compiler safeguards

The compiler validates the full tree and makes up to three attempts. A retry is triggered by either:

1. Pydantic schema failure; or
2. a deterministic fidelity check detecting one of the high-risk patterns currently covered:
   collapsed numeric ranges, collapsed “with at least one” logic, collapsed CPAP-adjustment
   duration, or weakened strict inequalities.

When repairing a schema-valid tree, the compiler includes the previous tree and requires the known
branch IDs to be preserved. The disk-cache key includes both the PDF bytes and compiler prompt, so a
prompt change recompiles previously cached policies.

These safeguards detect known failure shapes; they do not prove that the initial extraction contains
every policy branch or every criterion.

### Evidence representation

Patient evidence is not reduced to `found: true/false`. Each fact has one of four states:

| Evidence state | Meaning | Evaluation behavior |
|---|---|---|
| `DOCUMENTED` | The chart contains an assessed value or affirmative finding | Apply the deterministic predicate |
| `EXPLICITLY_ABSENT` | The chart explicitly denies an assessed finding | Treat as a documented negative; negated policy leaves can therefore pass |
| `NOT_DOCUMENTED` | The chart omits the fact or says the report/result is unavailable, pending, or unknown | `INSUFFICIENT_EVIDENCE` |
| `CONFLICTING` | Chart statements disagree and cannot be resolved | `INSUFFICIENT_EVIDENCE` |

The legacy `found` field remains as a derived compatibility projection. This distinction prevents
“no endoscopy report is included” from being treated as clinical proof that narrowing is absent.

The extractor receives only field name, expected raw type, unit, and clinical concept. Thresholds,
operators, and policy pass/fail language stay in code-owned evaluation.

### Deterministic evaluation and output

The evaluator returns `MET`, `NOT_MET`, or `INSUFFICIENT_EVIDENCE` using three-valued logic:

- `all_of`: any `NOT_MET` wins; otherwise unresolved evidence wins; otherwise `MET`.
- `any_of`: any `MET` wins; otherwise unresolved evidence wins; otherwise `NOT_MET`.
- `n_of(k)`: `MET` when at least `k` children pass; `NOT_MET` when even all unresolved children
  could not reach `k`; otherwise `INSUFFICIENT_EVIDENCE`.
- `unmappable`: always `INSUFFICIENT_EVIDENCE` with an `unmappable` flag.

`INSUFFICIENT_EVIDENCE` means the decision is unresolved, not necessarily that a missing document
exists. It can result from absent evidence, conflicting evidence, an unparseable value, or an
unmappable policy rule.

The response retains the complete evaluation tree but separately computes `decisive_findings` for
the UI. Passing OR/N-of alternatives are reduced to a sufficient witness, failed AND trees show the
actual failures, and unresolved trees show the unresolved paths. This prevents irrelevant branches
and unused alternatives from appearing as gaps.

### Second-model verification

Code selects leaves that are both weakly evidenced (missing or below the confidence threshold) and
structurally capable of changing the root verdict. Mistral independently re-extracts only those raw
facts. Agreement raises confidence. A value, presence, ordinal, or evidence-state disagreement:

- keeps the primary extractor's value;
- lowers its confidence; and
- adds `verifier_disagreement` for human review.

The verifier does **not** currently override facts or change the verdict. This makes it a review
signal, not a second decision-maker.

## What breaks first under a guideline change

1. **An omitted branch or criterion in the initial policy extraction.** Current checks can ensure a
   repair does not drop known branches, but there is no independent branch inventory against which
   to test the first tree. The intended fix is a small policy-index pass followed by per-branch
   compilation.
2. **Rules outside the predicate vocabulary.** Cross-visit event counting, unit conversion, complex
   temporal logic, or inter-branch dependencies become `unmappable` and therefore unresolved.
3. **Unsupported coverage disposition.** “Experimental,” “investigational,” and categorically
   non-covered language has no dedicated deterministic node/status yet. Mapping it to `unmappable`
   is conservative, but it produces `INSUFFICIENT_EVIDENCE` rather than a coverage denial.
4. **Compound language outside the current fidelity patterns.** The compiler checks several known
   collapse modes, but a differently worded conjunction could still be accepted as one leaf.
5. **New ordinal systems or units.** CEAP ordering is authored locally, and measurement parsing does
   not perform general unit conversion. Unknown values degrade to unresolved evidence.

## What breaks first under a messy chart

1. **Evidence phrased in an unexpected way.** The extractor can miss it, producing a false
   `NOT_DOCUMENTED` gap. Requested-field extraction and verbatim quotes make this reviewable, but do
   not eliminate extraction error.
2. **Conflicting notes.** They now remain explicitly `CONFLICTING`, but the UI currently presents all
   unresolved evidence similarly rather than giving each evidence state tailored workflow text.
3. **A vague or absent order.** Routing evaluates tied candidates or all branches and flags the route;
   the UI does not ask the user to resolve the procedure before evaluation.
4. **Scanned/image-only PDFs or layout-dependent evidence.** Local `pypdf` extraction can lose tables,
   reading order, handwriting, and page images. This is the primary reason to evaluate OpenAI PDF
   file inputs next.
5. **Malformed provider output or transport failures.** Fact-level validation degrades malformed
   individual facts to not documented. Compiler schema/fidelity failures retry up to three times.
   JSON-decoding, provider, and unexpected pipeline failures surface as HTTP 502 responses; there is
   no provider retry/backoff policy yet.

## Current validation and known operational limits

- The backend suite has 67 deterministic tests covering schemas, routing, evidence states,
  predicates, pivotality, compiler retries, verification, caching, and the pipeline. The frontend
  production build passes.
- Live regression results for the supplied advanced cases are: adult bariatric surgery `MET`, PVC
  ablation `NOT_MET`, and UPPP `INSUFFICIENT_EVIDENCE` with CPAP-adjustment duration and fiberoptic
  endoscopy as the two decisive unresolved items.
- Live verification currently depends on the pinned Mistral SDK (`mistralai>=1,<2`). The local
  development environment used for the advanced PDF regression had a newer incompatible SDK, so
  those live verdict checks ran without the Mistral review step. The verifier is covered by mocked
  tests and cannot change a verdict in the current design.
- There is no persistence for runs, human policy-tree approval, PHI/security hardening,
  multi-guideline reconciliation, appeals drafting, or EHR integration.
