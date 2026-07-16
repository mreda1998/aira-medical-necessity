from app.llm import FakeLLM
from app.models import Order, CriteriaTree
from app.router import extract_order, select_branch

TREE = CriteriaTree.model_validate({
    "guideline_id": "g", "title": "t", "branches": [
        {"branch_id": "saphenous", "vein_types": ["great_saphenous", "small_saphenous"],
         "procedure_label": "saph", "root": {"kind": "leaf", "id": "x", "predicate": "boolean",
         "field": "x", "threshold": True, "human_readable": "x"}},
        {"branch_id": "perforator", "vein_types": ["perforator"],
         "procedure_label": "perf", "root": {"kind": "leaf", "id": "y", "predicate": "boolean",
         "field": "y", "threshold": True, "human_readable": "y"}},
    ],
})


def test_extract_order_normalizes_vein():
    fake = FakeLLM([{"modality": "radiofrequency", "vein": "GSV",
                     "laterality": "right", "cpt": "36475", "raw": "RFA right GSV"}])
    order = extract_order("Plan: RFA of right GSV", fake)
    assert order.vein == "great_saphenous"   # normalized via canonical_vein
    assert order.modality == "radiofrequency"


def test_select_branch_single_match():
    branches, flag = select_branch(Order(vein="great_saphenous"), TREE)
    assert [b.branch_id for b in branches] == ["saphenous"]
    assert flag is None


def test_select_branch_ambiguous_falls_back_to_all():
    branches, flag = select_branch(Order(vein=None), TREE)
    assert len(branches) == 2
    assert flag == "ambiguous_route"
