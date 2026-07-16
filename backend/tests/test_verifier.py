from app.llm import FakeLLM
from app.models import AllOf, LeafNode, PredicateType, Fact
from app.evaluator import pivotal_leaf_ids
from app.verifier import leaves_to_verify, verify_facts

ROOT = AllOf(id="r", children=[
    LeafNode(id="a", predicate=PredicateType.BOOLEAN, field="fa", threshold=True, human_readable="a"),
    LeafNode(id="b", predicate=PredicateType.BOOLEAN, field="fb", threshold=True, human_readable="b"),
])


def test_leaves_to_verify_picks_pivotal_insufficient():
    facts = {"fa": Fact(field="fa", value=True, found=True, confidence=0.99)}
    # fb missing -> INSUFFICIENT and pivotal (all_of) -> should be verified
    field_ids = leaves_to_verify(ROOT, facts)
    assert "b" in field_ids
    assert "a" not in field_ids


def test_verify_flags_disagreement():
    facts = {
        "fa": Fact(field="fa", value=True, found=True, confidence=0.99),
        "fb": Fact(field="fb", value=None, found=False, confidence=0.2),
    }
    # verifier now claims fb IS found true
    verifier = FakeLLM([{"facts": [
        {"field": "fb", "value": True, "found": True, "source_span": {"text": "reflux noted"},
         "confidence": 0.8}]}])
    updated, flags = verify_facts("chart", ROOT, facts, ["b"], verifier)
    assert flags["fb"] == "verifier_disagreement"


def test_leaves_to_verify_includes_conf_0_7_band():
    # fb found, confidence 0.7 -> below the verifier's 0.75 net but above the
    # evaluator default's 0.6 net. Leaf swings the all_of verdict (a is MET).
    facts = {
        "fa": Fact(field="fa", value=True, found=True, confidence=0.99),
        "fb": Fact(field="fb", value=True, found=True, confidence=0.7),
    }
    assert "b" not in pivotal_leaf_ids(ROOT, facts)  # default 0.6 threshold excludes it
    assert "b" in leaves_to_verify(ROOT, facts)  # verifier's wider 0.75 net includes it


def test_verify_survives_malformed_verifier_output():
    facts = {
        "fa": Fact(field="fa", value=True, found=True, confidence=0.99),
        "fb": Fact(field="fb", value=None, found=False, confidence=0.2),
    }
    verifier = FakeLLM([{"facts": [
        {"value": True, "found": True},          # missing field key
        "junk",                                   # not a dict
        {"field": "fb", "value": [1, 2], "found": True},  # bad value type -> ValidationError
    ]}])
    updated, flags = verify_facts("chart", ROOT, facts, ["b"], verifier)
    assert flags == {}  # no verification signal, no crash


def test_values_agree_normalizes_formats():
    from app.verifier import _values_agree
    assert _values_agree(5, "5")
    assert _values_agree(5.0, "5 mm")
    assert _values_agree(True, "true")
    assert not _values_agree(5, "6 mm")
    assert not _values_agree(None, 5)


def test_verify_does_not_mutate_input_facts():
    facts = {
        "fa": Fact(field="fa", value=True, found=True, confidence=0.99),
        "fb": Fact(field="fb", value=True, found=True, confidence=0.5),
    }
    verifier = FakeLLM([{"facts": [
        {"field": "fb", "value": True, "found": True, "confidence": 0.8},
    ]}])
    updated, flags = verify_facts("chart", ROOT, facts, ["b"], verifier)
    assert facts["fb"].confidence == 0.5          # input untouched
    assert updated["fb"].confidence == 0.9        # boosted copy in output
