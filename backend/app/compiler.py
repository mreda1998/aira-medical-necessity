import re
from collections.abc import Callable

from pydantic import ValidationError

from .llm import LLM
from .models import CriteriaTree, Node, LeafNode, AllOf, NOf, PredicateType, UnmappableNode
from .pdf_extract import (
    ExtractedDocument,
    extract_text,
    resolve_source_span,
    select_compiler_document,
)
from . import store

COMPILER_INPUT_VERSION = "criteria-pages-v1"

COMPILER_SYSTEM = """You convert a payer medical-necessity guideline into a structured criteria tree.
Output JSON only, matching this schema:
{ "guideline_id": str, "title": str, "branches": [ {
    "branch_id": str, "procedure_codes": [str], "procedure_aliases": [str],
    "min_age": number|null, "max_age": number|null, "vein_types": [str],
    "procedure_label": str, "root": <node> } ] }

A <node> is one of:
  {"kind":"all_of","id":str,"children":[<node>...]}   (ALL must hold)
  {"kind":"any_of","id":str,"children":[<node>...]}   (ANY holds)
  {"kind":"n_of","id":str,"k":int,"children":[<node>...]}  (at least k hold)
  {"kind":"leaf","id":str,"predicate":P,"field":str,"threshold":<val>,"unit":str?,
   "negated":bool?,"human_readable":str,
   "source_span":{"text":str,"page":int,"section":str|null},"parse_confidence":float}
  {"kind":"unmappable","id":str,"human_readable":str,"reason":str,
   "source_span":{"text":str,"page":int,"section":str|null}}

P (the CLOSED predicate vocabulary — you MUST use only these) is one of:
  "boolean" | "numeric_gt" | "numeric_gte" | "numeric_lt" | "numeric_lte" |
  "ordinal_gte" | "duration_gte" | "existence"

Rules:
- Use canonical snake_case vein ids in vein_types: great_saphenous, small_saphenous,
  accessory_saphenous, perforator, tributary. For non-vein procedures use an empty list.
- Each branch must include generic applicability metadata. procedure_codes contains CPT/HCPCS
  codes explicitly associated with that procedure; procedure_aliases contains names and common
  abbreviations for the procedure. min_age/max_age are inclusive applicability bounds, not medical
  necessity criteria. Use null when the policy does not state an age applicability boundary.
- "one or more of the following" -> n_of with k=1.
- Durations like "at least 3 months" -> duration_gte with field in months, threshold 3.
- Upper-bounded timing such as "within 12 hours" -> numeric_lte over an elapsed-hours field with
  threshold 12 and unit "hours". Do not encode it as a negated duration_gte.
- CEAP class checks -> ordinal_gte with field "ceap_class", threshold like "C2".
- Vein size "at least 3 mm" -> numeric_gte, field "vein_diameter_mm", threshold 3, unit "mm".
- Preserve strict comparisons: ">15" -> numeric_gt and "<18" -> numeric_lt. Never weaken them
  to numeric_gte/numeric_lte.
- A bounded range such as "30-34.9" or "greater than 15 and less than 40" must become an all_of
  containing separate lower-bound and upper-bound leaves over the same raw field.
- Cosmetic / experimental / investigational branches: still emit the branch, but its criteria
  are structurally unmeetable — model them faithfully.
- If a criterion cannot be expressed with the closed vocabulary, emit an "unmappable" node with a
  reason. NEVER invent a predicate type.
- Every leaf must include a source_span with a verbatim guideline quote, the physical page from
  the nearest [[PDF PAGE n]] marker, and the nearest visible section heading when available.
  Quote the complete criterion sentence/bullet rather than a short repeated phrase so local code
  can verify it uniquely. Every leaf also needs parse_confidence in [0,1].
- When a single criterion sentence contains multiple ANDed clauses about different clinical
  facts (e.g. "There is demonstrated saphenous reflux AND CEAP class C2 or greater"), emit
  one leaf PER clause under an all_of — never collapse them into one leaf. A reflux
  requirement is its own boolean leaf (e.g. field "saphenous_reflux_demonstrated");
  a CEAP classification is its own ordinal_gte leaf (field "ceap_class").
- Every distinct evidentiary requirement in the guideline must map to its own leaf so a
  chart missing that specific evidence produces a visible gap.
- Split compound alternatives into raw atomic facts. For example, "therapy is ineffective,
  contraindicated, not tolerated, or not preferred" is an any_of of four leaves. Do not create a
  composite field whose value requires deciding whether the policy language is satisfied.
- Never encode negation in the field name (no "not_..."/"absence_of_..." fields). Name the
  field for the positive clinical fact (e.g. "insufficiency_secondary_to_dvt") and set
  "threshold": true and "negated": true on the leaf when the guideline requires its absence.
  Never combine negated=true with threshold=false; that double-negates the requirement.
- A required absence of "X or Y" means BOTH positive facts must be absent. Emit an all_of with
  a separate threshold=true, negated=true boolean leaf for X and for Y.
- Field names must name the raw clinical quantity or fact, never the comparison: use
  "ceap_class" (not "ceap_class_c2_or_greater"), "vein_diameter_mm" (not
  "varicosities_at_least_3mm"), "compression_therapy_months" (not
  "conservative_management_3_months"). The threshold belongs in "threshold", never in the
  field name — a field named after its threshold pushes chart extraction toward useless
  true/false answers instead of the measurable value.

Fidelity examples:
- INCORRECT: one numeric_gte leaf whose text says "BMI 30-34.9 with at least one comorbidity".
  CORRECT: an {"kind":"all_of","children":[...]} node containing two
  {"kind":"leaf","predicate":"numeric_gte|numeric_lte",...} nodes plus an n_of node.
- INCORRECT: one existence leaf for "CPAP intolerance despite adjustments over at least 1 month".
  CORRECT: an all_of with {"kind":"leaf","predicate":"boolean",...} for intolerance and
  {"kind":"leaf","predicate":"duration_gte",...} for adjustment duration.
- Node kind is structural only: all_of, any_of, n_of, leaf, or unmappable. Predicate names such as
  numeric_gt and existence always go in the predicate field of a kind=leaf node.
- A leaf's human_readable must be atomic and must not describe logical or numeric clauses absent
  from the emitted structure. A complete source_span quote may contain surrounding clauses when
  those clauses are represented by sibling or ancestor nodes in the same criterion group.
"""


def _leaf_text(leaf: LeafNode) -> str:
    source = leaf.source_span.text if leaf.source_span else ""
    return f"{leaf.human_readable} {source}".lower()


def _bounded_siblings(parent: Node | None, field: str) -> bool:
    if not isinstance(parent, AllOf):
        return False
    predicates = {
        child.predicate
        for child in parent.children
        if isinstance(child, LeafNode) and child.field == field
    }
    lower = {PredicateType.NUMERIC_GT, PredicateType.NUMERIC_GTE}
    upper = {PredicateType.NUMERIC_LT, PredicateType.NUMERIC_LTE}
    return bool(predicates & lower) and bool(predicates & upper)


def _has_n_of(parent: Node | None) -> bool:
    return isinstance(parent, AllOf) and any(isinstance(child, NOf) for child in parent.children)


def _has_duration(parent: Node | None) -> bool:
    return isinstance(parent, AllOf) and any(
        isinstance(child, LeafNode) and child.predicate == PredicateType.DURATION_GTE
        for child in parent.children
    )


def criteria_fidelity_issues(tree: CriteriaTree) -> list[str]:
    """Find high-risk cases where a leaf's prose contains logic it cannot represent."""
    issues: list[str] = []

    def walk(node: Node, parent: Node | None, branch_id: str) -> None:
        if isinstance(node, UnmappableNode):
            return
        if isinstance(node, LeafNode):
            text = _leaf_text(node)
            # The citation intentionally quotes the complete source criterion, so it may
            # contain clauses represented by nearby nodes. Collapse checks apply to the
            # leaf's atomic label; numeric fidelity still uses the source quote.
            structural_text = node.human_readable.lower()
            has_range = bool(re.search(r"\d+(?:\.\d+)?\s*[–—-]\s*\d+(?:\.\d+)?", text))
            if has_range and node.predicate in {
                PredicateType.NUMERIC_GT, PredicateType.NUMERIC_GTE,
                PredicateType.NUMERIC_LT, PredicateType.NUMERIC_LTE,
            } and not _bounded_siblings(parent, node.field):
                issues.append(
                    f"branch {branch_id} leaf {node.id}: numeric range is missing a lower or upper bound"
                )
            if "with at least one" in structural_text and not _has_n_of(parent):
                issues.append(
                    f"branch {branch_id} leaf {node.id}: 'with at least one' was collapsed into one leaf"
                )
            if "despite adjustments over at least" in structural_text and not _has_duration(parent):
                issues.append(
                    f"branch {branch_id} leaf {node.id}: adjustment duration was collapsed into one leaf"
                )
            if node.negated and node.threshold is False:
                issues.append(
                    f"branch {branch_id} leaf {node.id}: negated=true with threshold=false double-negates the requirement"
                )
            if (
                re.search(r"\bwithin\s+\d+(?:\.\d+)?\s+(?:hour|hours|day|days|month|months)\b", structural_text)
                and (node.predicate == PredicateType.DURATION_GTE or node.negated)
            ):
                issues.append(
                    f"branch {branch_id} leaf {node.id}: upper-bounded timing must use numeric_lte without negation"
                )
            if re.search(r"\bno\s+(?:evidence|history)\s+of\b.+\bor\b.+", structural_text):
                issues.append(
                    f"branch {branch_id} leaf {node.id}: required absence of alternatives must be split into separate negated leaves"
                )
            strict_gt = bool(re.search(r">(?![=])|greater than(?!\s+or equal)", text))
            strict_lt = bool(re.search(r"<(?![=])|less than(?!\s+or equal)", text))
            if strict_gt and node.predicate == PredicateType.NUMERIC_GTE:
                issues.append(
                    f"branch {branch_id} leaf {node.id}: strict greater-than was weakened to >="
                )
            if strict_lt and node.predicate == PredicateType.NUMERIC_LTE:
                issues.append(
                    f"branch {branch_id} leaf {node.id}: strict less-than was weakened to <="
                )
            return
        for child in node.children:
            walk(child, node, branch_id)

    for branch in tree.branches:
        walk(branch.root, None, branch.branch_id)
    return issues


def compile_guideline(
    text: str,
    llm: LLM,
    on_attempt: Callable[[int, int], None] | None = None,
) -> CriteriaTree:
    initial_user = f"GUIDELINE TEXT:\n{text}\n\nReturn the criteria tree JSON."
    prompt = initial_user
    expected_branches: set[str] | None = None
    last_problem = "unknown compiler failure"

    for attempt in range(1, 4):
        if on_attempt:
            on_attempt(attempt, 3)
        raw = llm.complete_json(COMPILER_SYSTEM, prompt)
        try:
            tree = CriteriaTree.model_validate(raw)
        except ValidationError as exc:
            compact_errors = "; ".join(
                f"{'.'.join(map(str, error['loc']))}: {error['msg']}"
                for error in exc.errors()[:8]
            )
            last_problem = "schema validation: " + compact_errors
            prompt = initial_user + (
                "\n\nThe previous output violated the required JSON schema. Return the complete tree "
                "again. Every atomic criterion must use kind=leaf and put numeric_gt, existence, "
                "and other predicate names in the predicate field. Errors:\n- "
                + compact_errors
            )
            continue

        issues = criteria_fidelity_issues(tree)
        current_branches = {branch.branch_id for branch in tree.branches}
        if expected_branches is not None:
            for missing_branch in sorted(expected_branches - current_branches):
                issues.append(f"repair dropped branch {missing_branch}")
        if not issues:
            return tree

        expected_branches = current_branches if expected_branches is None else expected_branches
        last_problem = "; ".join(issues[:8])
        # A validated tree already carries complete source quotes. Repair its
        # structure from that compact artifact instead of resending a very long
        # policy on every deterministic-fidelity retry.
        prompt = (
            "PREVIOUS TREE JSON (preserve every branch and unaffected criterion):\n"
            f"{tree.model_dump_json()}\n\nThe previous parse failed deterministic fidelity checks. "
            "Return a corrected full tree with the same branch coverage. Fix every issue below "
            "without dropping other criteria:\n- "
            + "\n- ".join(issues)
        )

    raise ValueError("guideline criteria failed validation after retries: " + last_problem)


def _enrich_source_spans(tree: CriteriaTree, document: ExtractedDocument) -> CriteriaTree:
    def enrich(node: Node) -> Node:
        if isinstance(node, (LeafNode, UnmappableNode)):
            return node.model_copy(update={
                "source_span": resolve_source_span(node.source_span, document.pages),
            })
        return node.model_copy(update={"children": [enrich(child) for child in node.children]})

    return tree.model_copy(update={
        "branches": [
            branch.model_copy(update={"root": enrich(branch.root)})
            for branch in tree.branches
        ],
    })


def compile_cached(
    data: bytes,
    llm: LLM,
    document: ExtractedDocument | None = None,
    on_cache: Callable[[bool], None] | None = None,
    on_attempt: Callable[[int, int], None] | None = None,
    on_selection: Callable[[int, int, str], None] | None = None,
) -> CriteriaTree:
    # Key on both the PDF bytes and the compiler prompt: a prompt change (e.g.
    # a fidelity fix like the ANDed-clause-splitting rule above) must bust the
    # cache for guidelines that were already compiled under the old prompt.
    h = store.content_hash(
        data
        + COMPILER_SYSTEM.encode("utf-8")
        + COMPILER_INPUT_VERSION.encode("utf-8")
    )
    cached = store.load_tree(h)
    if on_cache:
        on_cache(cached is not None)
    if cached is not None:
        return _enrich_source_spans(cached, document) if document else cached

    if document:
        selection = select_compiler_document(document)
        if on_selection:
            on_selection(
                selection.original_page_count,
                selection.selected_page_count,
                selection.strategy,
            )
        compiler_text = selection.document.marked_text
    else:
        compiler_text = extract_text(data)
    tree = compile_guideline(compiler_text, llm, on_attempt=on_attempt)
    if document:
        tree = _enrich_source_spans(tree, document)
    store.save_tree(h, tree)
    return tree
