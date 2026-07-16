from app.models import (
    Status, PredicateType, LeafNode, AllOf, NOf, CriteriaTree,
    CriteriaBranch, Fact, Order,
)


def test_leaf_node_roundtrips():
    leaf = LeafNode(
        id="l1", predicate=PredicateType.NUMERIC_GTE, field="vein_diameter_mm",
        threshold=3, unit="mm", human_readable="Varicosities at least 3 mm",
    )
    assert leaf.kind == "leaf"
    assert LeafNode.model_validate(leaf.model_dump()).threshold == 3


def test_tree_with_nested_nodes_parses_from_dict():
    tree = CriteriaTree.model_validate({
        "guideline_id": "02-33000-31",
        "title": "Varicose Veins",
        "branches": [{
            "branch_id": "great_or_small_saphenous",
            "vein_types": ["great_saphenous", "small_saphenous"],
            "procedure_label": "Treatment of great or small saphenous veins",
            "root": {
                "kind": "all_of", "id": "root", "children": [
                    {"kind": "leaf", "id": "reflux", "predicate": "boolean",
                     "field": "saphenous_reflux_demonstrated", "threshold": True,
                     "human_readable": "Demonstrated saphenous reflux"},
                    {"kind": "n_of", "id": "indications", "k": 1, "children": [
                        {"kind": "leaf", "id": "ulcer", "predicate": "existence",
                         "field": "venous_stasis_ulcer", "human_readable": "Ulceration"},
                    ]},
                ],
            },
        }],
    })
    assert tree.branches[0].root.kind == "all_of"
    assert tree.branches[0].root.children[1].k == 1


def test_status_and_order():
    assert Status.INSUFFICIENT.value == "INSUFFICIENT_EVIDENCE"
    o = Order(modality="radiofrequency", vein="great_saphenous", laterality="right", cpt="36475")
    assert o.vein == "great_saphenous"
