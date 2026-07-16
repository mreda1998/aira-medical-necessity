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
Guideline PDF ──pypdf──> page-aware text ──OpenAI──> criteria tree ──checks──> disk cache
                                                                  │
Chart PDF ──────pypdf──> page-aware text ──OpenAI──> order ──deterministic routing
                                                                  │
                                      OpenAI extracts requested raw facts only
                                                                  │
                                local quote-to-page source verification
                                                                  │
                                   deterministic three-valued evaluation
                                                                  │
                          Mistral re-extracts weak, pivotal facts when needed
                                                                  │
                               verdict + decisive findings + review flags
```

PDFs are currently converted to page-aware text locally with `pypdf`. A preflight records page and
text coverage, warns about long or partly unreadable documents, and rejects PDFs with no usable text
layer before the first model call. The application does **not** yet send PDFs as OpenAI file inputs,
and it continues to use Chat Completions JSON mode. For a policy longer than 40 pages, local code
uses a table-of-contents background/reference boundary only when it can do so deterministically;
otherwise it preserves the full policy. The full PDF always remains available for citation checks.

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

### How AND, OR, EITHER, ANY, and N-of become executable logic

The policy compiler identifies the logical wording and emits a recursive tree. The evaluator never
asks an LLM whether the overall rule is satisfied; it executes the accepted tree in code.

| Guideline wording | Tree representation | Executed meaning |
|---|---|---|
| “all of the following,” “each,” or clauses joined by `AND` | `all_of` | Every child must be `MET` |
| “either,” “any of the following,” or alternatives joined by `OR` | `any_of` | At least one child must be `MET` |
| “one or more of the following” | `n_of(k=1)` | At least one child must be `MET`, while preserving the explicit cardinality |
| “at least k of the following” | `n_of(k=k)` | At least `k` children must be `MET` |
| A single measurable or documentable requirement | `leaf` | Apply its authored predicate to one raw chart fact |
| A rule that cannot be expressed by the closed vocabulary | `unmappable` | Stop that path as `INSUFFICIENT_EVIDENCE` |

The nodes are recursively nestable, so an `any_of` can contain an `all_of`, and an `all_of` can
contain an `n_of` or another `any_of`. Bounded ranges are also structural: for example, BMI
30–34.9 becomes an `all_of` containing separate `numeric_gte(30)` and `numeric_lte(34.9)` leaves.
A required absence of “hemorrhage or dissection” becomes an `all_of` containing two positive-fact
leaves with `negated: true`; it is not collapsed into one ambiguous fact.

The implementation sequence is:

1. The compiler model maps policy language into `all_of`, `any_of`, `n_of`, and atomic leaf nodes.
2. Pydantic validates the complete recursive shape using the discriminated `Node` union. An unknown
   node kind or malformed child cannot reach evaluation.
3. Deterministic compiler checks reject known semantic collapses, including missing range bounds,
   “with at least one” represented as one leaf, combined required absences, double negation, and
   incorrectly negated upper-bounded timing.
4. Chart extraction receives only the raw fields requested by the leaves. It is not shown the
   Boolean operator or pass/fail threshold, so it cannot short-circuit the policy logic.
5. `evaluate()` recursively evaluates every child of the selected branch and combines the child
   statuses according to the node kind. The resulting full `EvalResult` tree is stored in
   `BranchResult.tree`.
6. Only after the root verdict exists does `decisive_findings()` derive the smaller explanation
   shown by the UI. This projection cannot change the tree or verdict.

The three Florida Blue baselines demonstrate the nested structures the code applies:

```text
Varicose-vein ablation (MET)
ALL
├── demonstrated saphenous reflux
├── CEAP class >= C2
├── varicosities >= 3 mm
└── ONE OR MORE
    ├── ulceration
    ├── recurrent thrombophlebitis
    ├── hemorrhage/recurrent bleeding
    └── ALL
        ├── persistent reflux-associated symptoms
        ├── significant activities-of-daily-living interference
        └── compression therapy >= 3 months without improvement

Carotid stenting (NOT_MET)
ALL
├── stenosis between 50% and 99%
├── qualifying recent focal cerebral ischemia
└── anatomic contraindication to carotid endarterectomy  ← explicitly absent

Intracranial mechanical thrombectomy (INSUFFICIENT_EVIDENCE)
ALL
├── qualifying proximal anterior-circulation occlusion
├── EITHER
│   ├── treatment within 12 hours
│   └── ALL
│       ├── treatment within 24 hours
│       └── qualifying clinical/imaging mismatch
├── substantial neurological deficit
├── salvageable brain tissue  ← not documented
└── ALL
    ├── no intracranial hemorrhage
    └── no arterial dissection
```

“Correctly identified” has a specific boundary here: the initial translation from policy prose to
the tree is model extraction, while schema validation, known fidelity checks, routing, predicate
comparisons, and Boolean evaluation are code. Given an accepted criteria tree and extracted facts,
the verdict is deterministic and reproducible. The safeguards substantially reduce known mapping
errors, but they cannot mathematically prove that the first policy extraction omitted no novel or
unexpectedly worded criterion; that limitation is why the source quotes, cached tree, regression
fixtures, and future human policy-tree approval remain important.

Each branch can carry applicability metadata independent of its medical-necessity criteria:
`procedure_codes`, `procedure_aliases`, `min_age`, `max_age`, and the legacy vascular
`vein_types`. Routing scores exact CPT/HCPCS and vessel matches, procedure aliases, specific label
tokens, and age bounds. A unique best match selects one branch. A tie returns the tied candidates;
no match returns zero branches with `policy_not_applicable`. A mismatch is therefore distinguished
from a clinical failure and does not trigger extraction against unrelated policy branches. A tied
best score still carries `ambiguous_route` and evaluates only those tied candidates.

### Compiler safeguards

The compiler validates the full tree and makes up to three attempts. A retry is triggered by either:

1. Pydantic schema failure; or
2. a deterministic fidelity check detecting one of the high-risk patterns currently covered:
   collapsed numeric ranges, collapsed “with at least one” logic, collapsed CPAP-adjustment
   duration, weakened strict inequalities, double-negated absence requirements, incorrectly
   negated upper-bounded timing, or collapsed required absences such as “no X or Y.”

When repairing a schema-valid tree, the compiler sends the previous tree and issues without
resending the source policy, and requires known branch IDs to be preserved. The disk-cache key
includes the PDF bytes, compiler prompt, and criteria-page selection version, so either behavior
change recompiles previously cached policies.

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

Guideline and chart quotes are resolved back to physical PDF pages by local code. Exact normalized
matches are preferred; page markers let the model disambiguate repeated wording, but the selected
page is accepted only when the quote actually occurs there. The source also carries the printed page
and a best-effort section heading. The UI links verified citations to the uploaded PDF at that page;
an unresolved location is labeled unverified and never changes the verdict.

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

The response retains the complete evaluation tree in `evaluated_branches[].tree`. The UI currently
renders `decisive_findings`, a projection computed only after the complete root tree has been
evaluated:

- a passing `all_of` retains all required children;
- a passing `any_of`/EITHER retains one sufficient passing alternative;
- a passing `n_of(k)` retains `k` sufficient passing alternatives;
- a failing tree retains the paths that made the rule fail; and
- an insufficient tree retains the unresolved paths that could still change the result.

Therefore, the shorter UI list is an explanation of the full decision, not the input to it. Unused
OR alternatives are hidden only after another alternative has already satisfied the parent rule.
The evaluator tests explicitly cover ALL precedence, ANY/EITHER precedence, N-of reachability,
nested pivotality, and explanation pruning in [test_evaluator.py](backend/tests/test_evaluator.py).

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
2. **Conflicting notes.** They remain explicitly `CONFLICTING` and are labeled separately from
   `NOT_DOCUMENTED` and `EXPLICITLY_ABSENT` in the UI, but still require human resolution.
3. **A vague or absent order.** A zero-score route now stops as `policy_not_applicable`; an equal
   best-score tie evaluates only the tied candidates and remains flagged for review.
4. **Scanned/image-only PDFs or layout-dependent evidence.** Preflight rejects a fully unreadable
   text layer and warns about partial coverage, but local `pypdf` can still lose tables, reading
   order, handwriting, and page images. OCR or vision remains future work.
5. **Malformed provider output or transport failures.** Fact-level validation degrades malformed
   individual facts to not documented. Compiler schema/fidelity failures retry up to three times.
   JSON-decoding, provider, and unexpected pipeline failures surface as HTTP 502 responses on the
   compatibility endpoint or typed error events on the streaming endpoint. There is no provider
   retry/backoff policy yet.

## Current validation and known operational limits

- The backend suite has 80 deterministic tests covering schemas, routing, evidence states,
  predicates, pivotality, compiler retries, criteria-page selection, streaming progress,
  verification, caching, and the pipeline. The frontend production build passes.
- The evaluation UI receives newline-delimited progress events for document preflight, cache use,
  criteria-page selection, compiler attempts, order extraction, routing, branch extraction,
  verification, and completion.
- Live Florida Blue regression results are: varicose-vein ablation `MET`, carotid stenting
  `NOT_MET`, intracranial thrombectomy `INSUFFICIENT_EVIDENCE`, and a pacemaker/vein-policy
  mismatch `policy_not_applicable` with zero evaluated branches.
- Live regression results for the supplied advanced cases are: adult bariatric surgery `MET`, PVC
  ablation `NOT_MET`, and UPPP `INSUFFICIENT_EVIDENCE` with CPAP-adjustment duration and fiberoptic
  endoscopy as the two decisive unresolved items.
- Live verification currently depends on the pinned Mistral SDK (`mistralai>=1,<2`). The local
  development environment used for the advanced PDF regression had a newer incompatible SDK, so
  those live verdict checks ran without the Mistral review step. The verifier is covered by mocked
  tests and cannot change a verdict in the current design.
- There is no persistence for runs, human policy-tree approval, PHI/security hardening,
  multi-guideline reconciliation, appeals drafting, or EHR integration.
