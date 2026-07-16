import json

from pydantic import ValidationError

from .llm import LLM
from .models import Node, LeafNode, UnmappableNode, Fact
from .evaluator import pivotal_leaf_ids
from .extractor import EXTRACTOR_SYSTEM
from .reference import parse_measurement, compare_ordinal


def _values_agree(a, b) -> bool:
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    if isinstance(a, bool) or isinstance(b, bool):
        def as_bool(v):
            if isinstance(v, bool):
                return v
            if isinstance(v, str):
                return v.strip().lower() in ("true", "yes", "1")
            return bool(v)
        return as_bool(a) == as_bool(b)
    na, nb = parse_measurement(a), parse_measurement(b)
    if na is not None and nb is not None:
        return na == nb
    return str(a).strip().lower() == str(b).strip().lower()


def _values_agree_for(predicate: str, a, b) -> bool:
    if a is None and b is None:
        return True
    if predicate == "ordinal_gte":
        try:
            return compare_ordinal(str(a), str(b)) == 0
        except (ValueError, TypeError):
            return str(a).strip().lower() == str(b).strip().lower()
    return _values_agree(a, b)


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
    """Pivotal leaves worth a second-model check: the verifier casts a wider
    confidence net (0.75) than the evaluator's default pivotal gate (0.6), so
    found-but-shaky facts in the [0.6, 0.75) band still get re-checked."""
    return pivotal_leaf_ids(root, facts, low_conf_threshold=0.75)


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
    user = (f"CHART:\n{chart_text}\n\nIndependently determine these fields:\n"
            f"{json.dumps(fields, indent=2)}\nReturn JSON {{\"facts\": [...]}}.")
    raw = verifier.complete_json(EXTRACTOR_SYSTEM, user)
    v_by_field: dict[str, Fact] = {}
    for item in raw.get("facts", []):
        if not isinstance(item, dict) or "field" not in item:
            continue  # malformed entry — no verification signal for this field
        try:
            v_by_field[item["field"]] = Fact.model_validate(item)
        except ValidationError:
            continue  # malformed fact — no verification signal for this field

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
        if vf.found != orig_found or not _values_agree_for(f["predicate"], vf.value, orig_val):
            flags[field] = "verifier_disagreement"
            # keep original value but drop confidence to force human review
            if orig:
                updated[field] = orig.model_copy(update={"confidence": min(orig.confidence, 0.3)})
        else:
            # agreement -> boost confidence
            if orig:
                updated[field] = orig.model_copy(update={"confidence": max(orig.confidence, 0.9)})
    return updated, flags
