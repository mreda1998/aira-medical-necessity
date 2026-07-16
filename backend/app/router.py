from .llm import LLM
from .models import Order, CriteriaTree, CriteriaBranch
from .reference import canonical_vein

ROUTER_SYSTEM = """Extract the ordered/planned procedure from a patient chart.
Return JSON: {"modality": str|null, "vein": str|null, "laterality": str|null,
"cpt": str|null, "raw": str|null}. "vein" should name the target vessel as written.
If no procedure is clearly ordered, set fields to null."""


def extract_order(chart_text: str, llm: LLM) -> Order:
    raw = llm.complete_json(ROUTER_SYSTEM, f"CHART:\n{chart_text}\n\nReturn the order JSON.")
    order = Order.model_validate(raw)
    if order.vein:
        order.vein = canonical_vein(order.vein) or order.vein
    return order


def select_branch(order: Order, tree: CriteriaTree) -> tuple[list[CriteriaBranch], str | None]:
    if order.vein:
        matches = [b for b in tree.branches if order.vein in b.vein_types]
        if len(matches) == 1:
            return matches, None
    return list(tree.branches), "ambiguous_route"
