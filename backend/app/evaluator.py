from typing import Optional

from .models import (
    Status, PredicateType, Node, LeafNode, UnmappableNode, AllOf, AnyOf, NOf,
    Fact, EvalResult, EvidenceState,
)
from .reference import compare_ordinal, parse_measurement


_FALSY_STRINGS = {"false", "no", "absent", "denied", "none", "negative", "0"}
_TRUTHY_STRINGS = {"true", "yes", "1", "present"}
_UNKNOWN_STRINGS = {
    "unknown", "unclear", "not documented", "not assessed", "not available",
    "unavailable", "pending", "conflicting",
}


def _is_explicit_negation(value) -> bool:
    """True when an extracted value explicitly denies the finding, as opposed
    to simply being unset. Covers real booleans and the string-y falsy values
    LLM extractors sometimes emit (e.g. "no", "denied", "absent")."""
    if value is False:
        return True
    if isinstance(value, str) and value.strip().lower() in _FALSY_STRINGS:
        return True
    return False


def _is_explicit_affirmation(value) -> bool:
    """True when an extracted value explicitly affirms the finding — the
    BOOLEAN-predicate counterpart to _is_explicit_negation. Covers real
    booleans and the string-y truthy values LLM extractors sometimes emit
    (e.g. "yes", "true", "present")."""
    if value is True:
        return True
    if isinstance(value, str) and value.strip().lower() in _TRUTHY_STRINGS:
        return True
    return False


def _apply_predicate(leaf: LeafNode, f: Fact) -> Status:
    p = leaf.predicate
    v = f.value
    if p == PredicateType.EXISTENCE:
        if isinstance(v, str) and v.strip().lower() in _UNKNOWN_STRINGS:
            return Status.INSUFFICIENT
        # found=True with an explicitly falsy value means the chart addresses
        # the finding and denies it — that is NOT_MET, not MET.
        if _is_explicit_negation(v):
            return Status.NOT_MET
        return Status.MET  # documented present (value True or unvalued mention)
    if p == PredicateType.BOOLEAN:
        want = leaf.threshold if leaf.threshold is not None else True
        if _is_explicit_negation(v):
            effective = False
        elif _is_explicit_affirmation(v):
            effective = True
        elif isinstance(v, str):
            return Status.INSUFFICIENT
        else:
            effective = bool(v)
        return Status.MET if effective == bool(want) else Status.NOT_MET
    if p in (
        PredicateType.NUMERIC_GT,
        PredicateType.NUMERIC_GTE,
        PredicateType.NUMERIC_LT,
        PredicateType.NUMERIC_LTE,
        PredicateType.DURATION_GTE,
    ):
        num = parse_measurement(v)
        thr = parse_measurement(leaf.threshold)
        if num is None or thr is None:
            return Status.INSUFFICIENT
        if p == PredicateType.NUMERIC_GT:
            return Status.MET if num > thr else Status.NOT_MET
        if p == PredicateType.NUMERIC_LT:
            return Status.MET if num < thr else Status.NOT_MET
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
    unavailable = f is not None and f.state in {
        EvidenceState.NOT_DOCUMENTED,
        EvidenceState.CONFLICTING,
    }
    if (
        f is None
        or unavailable
        or not f.found
        or (f.value is None and leaf.predicate != PredicateType.EXISTENCE)
    ):
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
    if not sts:
        return Status.INSUFFICIENT
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
    if not sts or k <= 0:
        return Status.INSUFFICIENT
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


def decisive_findings(node: Node, result: EvalResult) -> list[EvalResult]:
    """Return only leaf findings that explain the root result.

    Passing OR/N-of alternatives are pruned to a minimal witness. Failing AND
    nodes show only the branches that actually fail. Insufficient nodes show
    only unresolved paths. This keeps irrelevant alternatives out of the UI.
    """
    if isinstance(node, (LeafNode, UnmappableNode)):
        return [result]

    pairs = list(zip(node.children, result.children))
    selected: list[tuple[Node, EvalResult]]
    if result.status == Status.MET:
        if isinstance(node, AllOf):
            selected = pairs
        elif isinstance(node, AnyOf):
            selected = next(([pair] for pair in pairs if pair[1].status == Status.MET), [])
        else:  # NOf
            selected = [pair for pair in pairs if pair[1].status == Status.MET][:node.k]
    elif result.status == Status.NOT_MET:
        selected = [pair for pair in pairs if pair[1].status == Status.NOT_MET]
    else:
        selected = [pair for pair in pairs if pair[1].status == Status.INSUFFICIENT]

    findings: list[EvalResult] = []
    for child, child_result in selected:
        findings.extend(decisive_findings(child, child_result))

    deduped: list[EvalResult] = []
    seen: set[str] = set()
    for finding in findings:
        if finding.node_id not in seen:
            seen.add(finding.node_id)
            deduped.append(finding)
    return deduped


def _collect_leaves(node: Node) -> list[LeafNode]:
    if isinstance(node, LeafNode):
        return [node]
    if isinstance(node, UnmappableNode):
        return []
    leaves = []
    for c in node.children:
        leaves.extend(_collect_leaves(c))
    return leaves


def pivotal_leaf_ids(root: Node, facts: dict[str, Fact],
                      low_conf_threshold: float = 0.6) -> list[str]:
    """Leaves with weak evidence (missing or low-confidence) that are
    structurally able to move the root verdict — the re-extraction set."""
    pivotal = []
    for leaf in _collect_leaves(root):
        leaf_status = _eval_leaf(leaf, facts).status
        ev = facts.get(leaf.field)
        low_conf = ev is not None and ev.found and ev.confidence < low_conf_threshold
        if leaf_status != Status.INSUFFICIENT and not low_conf:
            continue  # solid evidence — re-extraction is pointless
        forced_met = evaluate(root, facts, {leaf.id: Status.MET}).status
        forced_not = evaluate(root, facts, {leaf.id: Status.NOT_MET}).status
        if forced_met != forced_not:  # structurally able to move the verdict
            pivotal.append(leaf.id)
    return pivotal
