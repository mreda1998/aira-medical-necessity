import json

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
