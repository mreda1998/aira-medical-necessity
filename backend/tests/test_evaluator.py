from app.models import (
    Status, PredicateType, LeafNode, AllOf, AnyOf, NOf, Fact,
)
from app.evaluator import evaluate, pivotal_leaf_ids


def leaf(id, pred, field, threshold=None, negated=False):
    return LeafNode(id=id, predicate=pred, field=field, threshold=threshold,
                    negated=negated, human_readable=id)


def fact(field, value=None, found=True):
    return Fact(field=field, value=value, found=found)


def facts(*fs):
    return {f.field: f for f in fs}


def test_leaf_met_not_met_insufficient():
    l = leaf("d", PredicateType.NUMERIC_GTE, "vein_diameter_mm", 3)
    assert evaluate(l, facts(fact("vein_diameter_mm", 4))).status == Status.MET
    assert evaluate(l, facts(fact("vein_diameter_mm", 2))).status == Status.NOT_MET
    assert evaluate(l, {}).status == Status.INSUFFICIENT


def test_numeric_leaf_with_boolean_value_is_insufficient():
    l = leaf("d", PredicateType.NUMERIC_GTE, "vein_diameter_mm", 3)
    assert evaluate(l, facts(fact("vein_diameter_mm", True))).status == Status.INSUFFICIENT


def test_ordinal_leaf():
    l = leaf("c", PredicateType.ORDINAL_GTE, "ceap_class", "C2")
    assert evaluate(l, facts(fact("ceap_class", "C3"))).status == Status.MET
    assert evaluate(l, facts(fact("ceap_class", "C1"))).status == Status.NOT_MET


def test_negated_leaf():
    l = leaf("dvt", PredicateType.BOOLEAN, "insufficiency_secondary_to_dvt",
             threshold=True, negated=True)
    assert evaluate(l, facts(fact("insufficiency_secondary_to_dvt", True))).status == Status.NOT_MET
    assert evaluate(l, facts(fact("insufficiency_secondary_to_dvt", False))).status == Status.MET


def test_all_of_precedence():
    node = AllOf(id="r", children=[
        leaf("a", PredicateType.BOOLEAN, "a", True),
        leaf("b", PredicateType.BOOLEAN, "b", True),
    ])
    assert evaluate(node, facts(fact("a", True), fact("b", True))).status == Status.MET
    assert evaluate(node, facts(fact("a", True), fact("b", False))).status == Status.NOT_MET
    assert evaluate(node, facts(fact("a", True))).status == Status.INSUFFICIENT  # b missing


def test_any_of_precedence():
    node = AnyOf(id="r", children=[
        leaf("a", PredicateType.BOOLEAN, "a", True),
        leaf("b", PredicateType.BOOLEAN, "b", True),
    ])
    assert evaluate(node, facts(fact("a", True))).status == Status.MET
    assert evaluate(node, facts(fact("a", False), fact("b", False))).status == Status.NOT_MET
    assert evaluate(node, {}).status == Status.INSUFFICIENT


def test_n_of_unreachable_is_not_met():
    node = NOf(id="r", k=2, children=[
        leaf("a", PredicateType.BOOLEAN, "a", True),
        leaf("b", PredicateType.BOOLEAN, "b", True),
        leaf("c", PredicateType.BOOLEAN, "c", True),
    ])
    # one MET, two NOT_MET → can't reach 2 → NOT_MET
    assert evaluate(node, facts(fact("a", True), fact("b", False), fact("c", False))).status == Status.NOT_MET
    # one MET, one missing → 1 MET + 1 INSUFFICIENT >= 2 possible → INSUFFICIENT
    assert evaluate(node, facts(fact("a", True), fact("b", False))).status == Status.INSUFFICIENT
    # two MET → MET
    assert evaluate(node, facts(fact("a", True), fact("b", True))).status == Status.MET


def test_pivotal_leaf_detection():
    # root = all_of(a, b); a is MET, b is missing → b is pivotal, a is not.
    node = AllOf(id="r", children=[
        leaf("a", PredicateType.BOOLEAN, "a", True),
        leaf("b", PredicateType.BOOLEAN, "b", True),
    ])
    ids = pivotal_leaf_ids(node, facts(fact("a", True)))
    assert "b" in ids
    assert "a" not in ids


def test_pivotal_flags_all_jointly_missing_leaves():
    # all_of with two missing leaves: BOTH must be flagged (this was the bug)
    node = AllOf(id="r", children=[
        leaf("a", PredicateType.BOOLEAN, "a", True),
        leaf("b", PredicateType.BOOLEAN, "b", True),
        leaf("c", PredicateType.BOOLEAN, "c", True),
    ])
    ids = pivotal_leaf_ids(node, facts(fact("a", True)))
    assert set(ids) == {"b", "c"}


def test_pivotal_n_of_shortfall_two():
    node = NOf(id="r", k=2, children=[
        leaf("a", PredicateType.BOOLEAN, "a", True),
        leaf("b", PredicateType.BOOLEAN, "b", True),
        leaf("c", PredicateType.BOOLEAN, "c", True),
    ])
    ids = pivotal_leaf_ids(node, facts(fact("a", True)))
    assert set(ids) == {"b", "c"}


def test_pivotal_ignores_missing_leaf_when_verdict_already_conclusive():
    # any_of already MET: missing leaf cannot swing anything
    node = AnyOf(id="r", children=[
        leaf("a", PredicateType.BOOLEAN, "a", True),
        leaf("b", PredicateType.BOOLEAN, "b", True),
    ])
    assert pivotal_leaf_ids(node, facts(fact("a", True))) == []


def test_pivotal_includes_low_confidence_found_fact():
    node = AllOf(id="r", children=[
        leaf("a", PredicateType.BOOLEAN, "a", True),
        leaf("b", PredicateType.BOOLEAN, "b", True),
    ])
    fs = facts(fact("a", True), fact("b", True))
    fs["b"].confidence = 0.4  # found but shaky
    assert pivotal_leaf_ids(node, fs) == ["b"]


def test_existence_explicit_negation_is_not_met():
    l = leaf("u", PredicateType.EXISTENCE, "ulcer")
    assert evaluate(l, facts(fact("ulcer", False))).status == Status.NOT_MET
    assert evaluate(l, facts(fact("ulcer", "no"))).status == Status.NOT_MET
    assert evaluate(l, facts(fact("ulcer", "denied"))).status == Status.NOT_MET
    assert evaluate(l, facts(fact("ulcer", True))).status == Status.MET
    assert evaluate(l, facts(fact("ulcer", None))).status == Status.MET  # documented mention, no bool
    assert evaluate(l, {}).status == Status.INSUFFICIENT


def test_empty_conjunction_nodes_are_insufficient_not_met():
    assert evaluate(AllOf(id="r", children=[]), {}).status == Status.INSUFFICIENT
    assert evaluate(NOf(id="r", k=0, children=[]), {}).status == Status.INSUFFICIENT
    assert evaluate(NOf(id="r", k=2, children=[]), {}).status == Status.INSUFFICIENT


def test_boolean_predicate_coerces_string_negation():
    l = leaf("b", PredicateType.BOOLEAN, "b", True)
    assert evaluate(l, facts(fact("b", "no"))).status == Status.NOT_MET
    assert evaluate(l, facts(fact("b", "false"))).status == Status.NOT_MET
    assert evaluate(l, facts(fact("b", "yes"))).status == Status.MET
    assert evaluate(l, facts(fact("b", True))).status == Status.MET


def test_boolean_predicate_unrecognized_string_is_insufficient():
    l = leaf("b", PredicateType.BOOLEAN, "b", True)
    assert evaluate(l, facts(fact("b", "unclear finding"))).status == Status.INSUFFICIENT
    assert evaluate(l, facts(fact("b", "not assessed"))).status == Status.INSUFFICIENT
    assert evaluate(l, facts(fact("b", "0"))).status == Status.NOT_MET
    assert evaluate(l, facts(fact("b", "1"))).status == Status.MET


def test_pivotal_leaf_ids_custom_threshold_widens_low_conf_band():
    # b found at confidence 0.7: default (0.6) threshold treats it as solid
    # evidence and excludes it; a wider 0.75 threshold (as used by the
    # verifier) includes it since it still swings the all_of verdict.
    node = AllOf(id="r", children=[
        leaf("a", PredicateType.BOOLEAN, "a", True),
        leaf("b", PredicateType.BOOLEAN, "b", True),
    ])
    fs = facts(fact("a", True), fact("b", True))
    fs["b"].confidence = 0.7
    assert pivotal_leaf_ids(node, fs) == []
    assert pivotal_leaf_ids(node, fs, low_conf_threshold=0.75) == ["b"]
