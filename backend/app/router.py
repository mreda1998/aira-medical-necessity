import re

from .llm import LLM
from .models import Order, CriteriaTree, CriteriaBranch
from .reference import canonical_vein

ROUTER_SYSTEM = """Extract the ordered/planned procedure from a patient chart.
Return JSON: {"modality": str|null, "vein": str|null, "laterality": str|null,
"cpt": str|null, "raw": str|null, "patient_age": number|null}. "vein" should name the target
vessel as written. patient_age is the documented age at the time of the requested procedure.
If no procedure is clearly ordered, set fields to null."""


def extract_order(chart_text: str, llm: LLM) -> Order:
    raw = llm.complete_json(ROUTER_SYSTEM, f"CHART:\n{chart_text}\n\nReturn the order JSON.")
    order = Order.model_validate(raw)
    if order.vein:
        order.vein = canonical_vein(order.vein) or order.vein
    return order


def _normalize_code(value: str | None) -> str:
    return re.sub(r"[^A-Z0-9]", "", (value or "").upper())


def _tokens(value: str | None) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", (value or "").lower())
        if token not in {"the", "a", "an", "of", "for", "with", "as", "procedure"}
    }


def _text_match(alias: str, order_text: str) -> bool:
    alias_tokens = _tokens(alias)
    order_tokens = _tokens(order_text)
    if not alias_tokens or not order_tokens:
        return False
    # Exact token containment handles labels with punctuation or parenthetical
    # abbreviations while avoiding broad substring matches.
    return alias_tokens <= order_tokens or order_tokens <= alias_tokens


def _age_applies(order: Order, branch: CriteriaBranch) -> bool:
    if order.patient_age is None:
        return True
    if branch.min_age is not None and order.patient_age < branch.min_age:
        return False
    if branch.max_age is not None and order.patient_age > branch.max_age:
        return False
    return True


def _match_score(order: Order, branch: CriteriaBranch) -> int:
    if not _age_applies(order, branch):
        return 0

    score = 0
    order_code = _normalize_code(order.cpt)
    if order_code and order_code in {_normalize_code(c) for c in branch.procedure_codes}:
        score = max(score, 100)
    if order.vein and order.vein in branch.vein_types:
        score = max(score, 100)

    order_text = " ".join(filter(None, [order.raw, order.modality]))
    order_tokens = _tokens(order_text)
    aliases = [*branch.procedure_aliases, branch.procedure_label]
    if any(_text_match(alias, order_text) for alias in aliases):
        score += 30
    # Shared billing codes can span multiple indications. Specific words in
    # the branch label (e.g. ventricular vs atrial) break those ties without
    # asking an LLM to choose the branch.
    score += min(len(_tokens(branch.procedure_label) & order_tokens), 5) * 5
    return score


def select_branch(order: Order, tree: CriteriaTree) -> tuple[list[CriteriaBranch], str | None]:
    scored = [(score, branch) for branch in tree.branches if (score := _match_score(order, branch))]
    if scored:
        best = max(score for score, _ in scored)
        matches = [branch for score, branch in scored if score == best]
        if len(matches) == 1:
            return matches, None
        return matches, "ambiguous_route"
    # A policy mismatch is not a clinical failure and must not trigger costly
    # extraction against every unrelated branch.
    return [], "policy_not_applicable"
