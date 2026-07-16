from .llm import LLM
from .models import CriteriaTree
from .pdf_extract import extract_text
from . import store

COMPILER_SYSTEM = """You convert a payer medical-necessity guideline into a structured criteria tree.
Output JSON only, matching this schema:
{ "guideline_id": str, "title": str, "branches": [ {
    "branch_id": str, "vein_types": [str], "procedure_label": str, "root": <node> } ] }

A <node> is one of:
  {"kind":"all_of","id":str,"children":[<node>...]}   (ALL must hold)
  {"kind":"any_of","id":str,"children":[<node>...]}   (ANY holds)
  {"kind":"n_of","id":str,"k":int,"children":[<node>...]}  (at least k hold)
  {"kind":"leaf","id":str,"predicate":P,"field":str,"threshold":<val>,"unit":str?,
   "negated":bool?,"human_readable":str,"source_span":{"text":str},"parse_confidence":float}
  {"kind":"unmappable","id":str,"human_readable":str,"reason":str,"source_span":{"text":str}}

P (the CLOSED predicate vocabulary — you MUST use only these) is one of:
  "boolean" | "numeric_gte" | "numeric_lte" | "ordinal_gte" | "duration_gte" | "existence"

Rules:
- Use canonical snake_case vein ids in vein_types: great_saphenous, small_saphenous,
  accessory_saphenous, perforator, tributary.
- "one or more of the following" -> n_of with k=1.
- Durations like "at least 3 months" -> duration_gte with field in months, threshold 3.
- CEAP class checks -> ordinal_gte with field "ceap_class", threshold like "C2".
- Vein size "at least 3 mm" -> numeric_gte, field "vein_diameter_mm", threshold 3, unit "mm".
- Cosmetic / experimental / investigational branches: still emit the branch, but its criteria
  are structurally unmeetable — model them faithfully.
- If a criterion cannot be expressed with the closed vocabulary, emit an "unmappable" node with a
  reason. NEVER invent a predicate type.
- Every leaf must include a source_span quoting the guideline text it came from and a
  parse_confidence in [0,1].
"""


def compile_guideline(text: str, llm: LLM) -> CriteriaTree:
    user = f"GUIDELINE TEXT:\n{text}\n\nReturn the criteria tree JSON."
    raw = llm.complete_json(COMPILER_SYSTEM, user)
    return CriteriaTree.model_validate(raw)


def compile_cached(data: bytes, llm: LLM) -> CriteriaTree:
    h = store.content_hash(data)
    cached = store.load_tree(h)
    if cached is not None:
        return cached
    tree = compile_guideline(extract_text(data), llm)
    store.save_tree(h, tree)
    return tree
