from app.llm import FakeLLM
from app.models import AllOf, LeafNode, PredicateType
from app.extractor import required_fields, extract_facts


ROOT = AllOf(id="r", children=[
    LeafNode(id="a", predicate=PredicateType.NUMERIC_GTE, field="vein_diameter_mm",
             threshold=3, unit="mm", human_readable="Varicosities >= 3 mm"),
    LeafNode(id="b", predicate=PredicateType.BOOLEAN, field="saphenous_reflux_demonstrated",
             threshold=True, human_readable="Demonstrated reflux"),
])


def test_required_fields_lists_every_leaf():
    fields = {f["field"] for f in required_fields(ROOT)}
    assert fields == {"vein_diameter_mm", "saphenous_reflux_demonstrated"}


def test_extract_facts_maps_and_defaults_missing():
    fake = FakeLLM([{"facts": [
        {"field": "vein_diameter_mm", "value": 5, "unit": "mm", "found": True,
         "source_span": {"text": "GSV 5mm"}, "confidence": 0.9},
        # reflux omitted entirely by the model -> must become found: false
    ]}])
    facts = extract_facts("chart text", ROOT, fake)
    assert facts["vein_diameter_mm"].value == 5
    assert facts["saphenous_reflux_demonstrated"].found is False
    assert "vein_diameter_mm" in fake.calls[0]["user"]  # guided by the field list
