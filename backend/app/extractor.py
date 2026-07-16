import json

from pydantic import ValidationError

from .llm import LLM
from .models import Node, LeafNode, UnmappableNode, Fact
from .pdf_extract import ExtractedDocument, resolve_source_span

EXTRACTOR_SYSTEM = """You extract clinical facts from a patient chart, but ONLY the fields requested.
For each requested field return: {"field": str, "value": <number|string|bool|null>,
"unit": str|null, "state": S,
"source_span": {"text": <complete verbatim quote from chart>, "page": int, "section": str|null},
"confidence": float}, where S is exactly one of DOCUMENTED, EXPLICITLY_ABSENT, NOT_DOCUMENTED,
or CONFLICTING.

Use the nearest [[PDF PAGE n]] marker for page and the nearest visible section heading for section.
The quote must not include the page marker. Prefer a complete sentence that uniquely identifies the
source location rather than a short repeated phrase.

Evidence-state rules:
- DOCUMENTED: the clinical value/finding was actually assessed and is present in the chart.
- EXPLICITLY_ABSENT: the clinical finding was assessed and explicitly denied (e.g. "no ulceration").
  Use value=false.
- NOT_DOCUMENTED: the chart says a report/result is absent, pending, unknown, unavailable, or simply
  does not address the fact. Use value=null. A sentence saying documentation is missing is NOT a
  negative clinical finding.
- CONFLICTING: chart statements disagree and the requested fact cannot be resolved. Use value=null.

Examples: "No fiberoptic endoscopy report is included" -> NOT_DOCUMENTED, not EXPLICITLY_ABSENT.
"It is unknown whether retropalatal narrowing is present" -> NOT_DOCUMENTED.
"No retropalatal narrowing was seen on endoscopy" -> EXPLICITLY_ABSENT.
"One note says PAP stopped; another says it continued" -> CONFLICTING when duration/tolerance cannot
be resolved.

Do NOT infer facts that are not supported by the chart text.
For numeric, duration, or classification fields (the requested field list shows each field's
expected_type and unit), "value" must be the actual quantity or class from the chart ("5 mm",
6.5, "C4a", "4 months") — never true/false. Reserve booleans for boolean/existence fields.
Return JSON: {"facts": [ ... ]}."""


def field_spec(leaf: LeafNode) -> dict:
    """Describe a raw chart field without exposing the policy comparison.

    Thresholds and operators belong to the evaluator. Including them in the
    extraction request encourages a model to return whether a criterion passes
    instead of returning the observed value (for example ``false`` vs BMI 33.3).
    """
    if leaf.predicate.value.startswith("numeric_") or leaf.predicate.value == "duration_gte":
        expected_type = "number"
    elif leaf.predicate.value == "ordinal_gte":
        expected_type = "string"
    else:
        expected_type = "boolean"
    return {
        "field": leaf.field,
        "expected_type": expected_type,
        "unit": leaf.unit,
        "clinical_concept": leaf.field.replace("_", " "),
    }


def required_fields(root: Node) -> list[dict]:
    out: list[dict] = []

    def walk(n: Node):
        if isinstance(n, LeafNode):
            out.append(field_spec(n))
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


def extract_facts(
    chart_text: str,
    root: Node,
    llm: LLM,
    document: ExtractedDocument | None = None,
) -> dict[str, Fact]:
    fields = required_fields(root)
    user = (f"CHART:\n{chart_text}\n\nExtract these fields:\n{json.dumps(fields, indent=2)}\n"
            "Return JSON {\"facts\": [...]}.")
    raw = llm.complete_json(EXTRACTOR_SYSTEM, user)
    by_field: dict[str, Fact] = {}
    for item in (raw.get("facts") or []):
        if not isinstance(item, dict) or "field" not in item:
            continue  # malformed entry — the field will default to found=False
        try:
            fact = Fact.model_validate(item)
            if document:
                fact = fact.model_copy(update={
                    "source_span": resolve_source_span(fact.source_span, document.pages),
                })
            by_field[item["field"]] = fact
        except ValidationError:
            continue  # malformed fact — degrade to found=False for this field
    result: dict[str, Fact] = {}
    for f in fields:
        result[f["field"]] = by_field.get(f["field"], Fact(field=f["field"], found=False))
    return result
