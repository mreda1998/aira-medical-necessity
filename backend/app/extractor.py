import json

from pydantic import ValidationError

from .llm import LLM
from .models import Node, LeafNode, UnmappableNode, Fact

EXTRACTOR_SYSTEM = """You extract clinical facts from a patient chart, but ONLY the fields requested.
For each requested field return: {"field": str, "value": <number|string|bool|null>,
"unit": str|null, "found": bool, "source_span": {"text": <verbatim quote from chart>},
"confidence": float}. If the chart does not document a field, return found=false and value=null.
If the chart explicitly denies or negates a finding (e.g. "no ulceration", "denies bleeding"),
return found=true with value=false — reserve found=false for findings the chart does not
address at all.
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
    by_field: dict[str, Fact] = {}
    for item in raw.get("facts", []):
        if not isinstance(item, dict) or "field" not in item:
            continue  # malformed entry — the field will default to found=False
        try:
            by_field[item["field"]] = Fact.model_validate(item)
        except ValidationError:
            continue  # malformed fact — degrade to found=False for this field
    result: dict[str, Fact] = {}
    for f in fields:
        result[f["field"]] = by_field.get(f["field"], Fact(field=f["field"], found=False))
    return result
