from app.llm import FakeLLM
from app.compiler import compile_guideline, COMPILER_SYSTEM
from app.models import CriteriaTree

TREE_JSON = {
    "guideline_id": "02-33000-31",
    "title": "Varicose Veins",
    "branches": [{
        "branch_id": "great_or_small_saphenous",
        "vein_types": ["great_saphenous", "small_saphenous"],
        "procedure_label": "Treatment of great or small saphenous veins",
        "root": {"kind": "all_of", "id": "root", "children": [
            {"kind": "leaf", "id": "reflux", "predicate": "boolean",
             "field": "saphenous_reflux_demonstrated", "threshold": True,
             "human_readable": "Demonstrated saphenous reflux"},
        ]},
    }],
}


def test_compile_guideline_validates_tree():
    fake = FakeLLM([TREE_JSON])
    tree = compile_guideline("some guideline text", fake)
    assert isinstance(tree, CriteriaTree)
    assert tree.branches[0].vein_types == ["great_saphenous", "small_saphenous"]
    # prompt actually included the guideline text
    assert "some guideline text" in fake.calls[0]["user"]
    assert "closed" in COMPILER_SYSTEM.lower()  # instructs the closed predicate vocabulary
