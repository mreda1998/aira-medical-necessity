from app.models import (
    Status, PredicateType, LeafNode, AllOf, NOf, CriteriaTree,
    CriteriaBranch, Fact, Order, SourceSpan, AnyOf, UnmappableNode, EvalResult,
    EvidenceState,
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


def test_fact_evidence_state_is_source_of_truth_with_legacy_projection():
    missing = Fact(field="endoscopy", state=EvidenceState.NOT_DOCUMENTED, value=True)
    assert missing.found is False
    assert missing.value is None

    absent = Fact(field="endoscopy", state=EvidenceState.EXPLICITLY_ABSENT)
    assert absent.found is True
    assert absent.value is False

    legacy = Fact(field="ulcer", found=True, value=False)
    assert legacy.state == EvidenceState.EXPLICITLY_ABSENT


def test_untested_types_roundtrip():
    span = SourceSpan(text="quote from guideline")
    assert SourceSpan.model_validate(span.model_dump()).text == "quote from guideline"

    any_of = AnyOf(id="r", children=[
        LeafNode(id="a", predicate=PredicateType.BOOLEAN, field="a", threshold=True, human_readable="a"),
    ])
    assert any_of.kind == "any_of"
    assert AnyOf.model_validate(any_of.model_dump()).children[0].id == "a"

    um = UnmappableNode(id="u", human_readable="could not map", reason="novel modality")
    assert UnmappableNode.model_validate(um.model_dump()).reason == "novel modality"

    res = EvalResult(node_id="root", kind="all_of", status=Status.INSUFFICIENT, children=[
        EvalResult(node_id="leaf1", kind="leaf", status=Status.MET, human_readable="child"),
    ])
    round_tripped = EvalResult.model_validate(res.model_dump())
    assert round_tripped.children[0].status == Status.MET
    assert round_tripped.children[0].human_readable == "child"
