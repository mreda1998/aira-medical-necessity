import json

from .llm import LLM
from .models import Node, LeafNode, UnmappableNode, Fact

EXTRACTOR_SYSTEM = """You extract clinical facts from a patient chart, but ONLY the fields requested.
For each requested field return: {"field": str, "value": <number|string|bool|null>,
"unit": str|null, "found": bool, "source_span": {"text": <verbatim quote from chart>},
"confidence": float}. If the chart does not document a field, return found=false and value=null.
Do NOT infer facts that are not supported by the chart text. Return JSON: {"facts": [ ... ]}."""


def required_fields(root: Node) -> list[dict]:
    out: list[dict] = []

    def walk(n: Node):
        if isinstance(n, LeafNode):
            out.append({"field": n.field, "predicate": n.predicate.value,
                        "human_readable": n.human_readable,
                        "threshold": n.threshold, "unit": n.unit})
        elif isinstance(n, UnmappableNode):
            return
        else:
            for c in n.children:
                walk(c)

    walk(root)
    # de-dupe by field, keep first
    seen, deduped = set(), []
    for f in out:
        if f["field"] not in seen:
            seen.add(f["field"])
            deduped.append(f)
    return deduped


def extract_facts(chart_text: str, root: Node, llm: LLM) -> dict[str, Fact]:
    fields = required_fields(root)
    user = (f"CHART:\n{chart_text}\n\nExtract these fields:\n{json.dumps(fields, indent=2)}\n"
            "Return JSON {\"facts\": [...]}.")
    raw = llm.complete_json(EXTRACTOR_SYSTEM, user)
    by_field = {f["field"]: Fact.model_validate(f) for f in raw.get("facts", [])}
    result: dict[str, Fact] = {}
    for f in fields:
        result[f["field"]] = by_field.get(f["field"], Fact(field=f["field"], found=False))
    return result
