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


def test_select_branch_no_match_returns_policy_not_applicable():
    branches, flag = select_branch(Order(vein=None), TREE)
    assert branches == []
    assert flag == "policy_not_applicable"


def test_select_branch_equal_best_scores_remain_ambiguous():
    tree = CriteriaTree.model_validate({
        "guideline_id": "g", "title": "t", "branches": [
            {"branch_id": "one", "procedure_codes": ["12345"], "procedure_label": "one",
             "root": {"kind": "leaf", "id": "x", "predicate": "existence",
                      "field": "x", "human_readable": "x"}},
            {"branch_id": "two", "procedure_codes": ["12345"], "procedure_label": "two",
             "root": {"kind": "leaf", "id": "y", "predicate": "existence",
                      "field": "y", "human_readable": "y"}},
        ],
    })
    branches, flag = select_branch(Order(cpt="12345"), tree)
    assert [branch.branch_id for branch in branches] == ["one", "two"]
    assert flag == "ambiguous_route"


def test_select_branch_uses_procedure_code_and_age_applicability():
    tree = CriteriaTree.model_validate({
        "guideline_id": "g", "title": "Bariatric", "branches": [
            {
                "branch_id": "adult", "procedure_codes": ["43775"], "min_age": 18,
                "procedure_label": "Adult sleeve gastrectomy",
                "root": {"kind": "leaf", "id": "a", "predicate": "existence",
                         "field": "x", "human_readable": "x"},
            },
            {
                "branch_id": "pediatric", "procedure_codes": ["43775"], "max_age": 17,
                "procedure_label": "Pediatric sleeve gastrectomy",
                "root": {"kind": "leaf", "id": "p", "predicate": "existence",
                         "field": "x", "human_readable": "x"},
            },
        ],
    })
    branches, flag = select_branch(Order(cpt="43775", patient_age=44), tree)
    assert [branch.branch_id for branch in branches] == ["adult"]
    assert flag is None


def test_select_branch_uses_generic_procedure_alias():
    tree = CriteriaTree.model_validate({
        "guideline_id": "g", "title": "OSA", "branches": [
            {
                "branch_id": "uppp", "procedure_aliases": ["uvulopalatopharyngoplasty"],
                "procedure_label": "Uvulopalatopharyngoplasty (UPPP)",
                "root": {"kind": "leaf", "id": "u", "predicate": "existence",
                         "field": "x", "human_readable": "x"},
            },
            {
                "branch_id": "jaw", "procedure_aliases": ["maxillomandibular advancement"],
                "procedure_label": "Jaw realignment surgery",
                "root": {"kind": "leaf", "id": "j", "predicate": "existence",
                         "field": "x", "human_readable": "x"},
            },
        ],
    })
    branches, flag = select_branch(
        Order(raw="Uvulopalatopharyngoplasty as sole procedure", cpt="42145"), tree
    )
    assert [branch.branch_id for branch in branches] == ["uppp"]
    assert flag is None
