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


def _collect_leaves(node: Node) -> list[LeafNode]:
    if isinstance(node, LeafNode):
        return [node]
    if isinstance(node, UnmappableNode):
        return []
    leaves = []
    for c in node.children:
        leaves.extend(_collect_leaves(c))
    return leaves


def pivotal_leaf_ids(root: Node, facts: dict[str, Fact]) -> list[str]:
    """Leaves with weak evidence (missing or low-confidence) that are
    structurally able to move the root verdict — the re-extraction set."""
    pivotal = []
    for leaf in _collect_leaves(root):
        leaf_status = _eval_leaf(leaf, facts).status
        ev = facts.get(leaf.field)
        low_conf = ev is not None and ev.found and ev.confidence < 0.6
        if leaf_status != Status.INSUFFICIENT and not low_conf:
            continue  # solid evidence — re-extraction is pointless
        forced_met = evaluate(root, facts, {leaf.id: Status.MET}).status
        forced_not = evaluate(root, facts, {leaf.id: Status.NOT_MET}).status
        if forced_met != forced_not:  # structurally able to move the verdict
            pivotal.append(leaf.id)
    return pivotal
