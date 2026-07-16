from app.llm import FakeLLM
from app.models import AllOf, LeafNode, PredicateType
from app.extractor import required_fields, extract_facts
from app.pdf_extract import ExtractedDocument, PageText


ROOT = AllOf(id="r", children=[
    LeafNode(id="a", predicate=PredicateType.NUMERIC_GTE, field="vein_diameter_mm",
             threshold=3, unit="mm", human_readable="Varicosities >= 3 mm"),
    LeafNode(id="b", predicate=PredicateType.BOOLEAN, field="saphenous_reflux_demonstrated",
             threshold=True, human_readable="Demonstrated reflux"),
])


def test_required_fields_lists_every_leaf():
    fields = {f["field"] for f in required_fields(ROOT)}
    assert fields == {"vein_diameter_mm", "saphenous_reflux_demonstrated"}
    numeric = next(f for f in required_fields(ROOT) if f["field"] == "vein_diameter_mm")
    assert numeric["expected_type"] == "number"
    assert "threshold" not in numeric
    assert "predicate" not in numeric


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


def test_extract_facts_resolves_verbatim_quote_to_chart_page():
    document = ExtractedDocument(pages=(
        PageText(number=1, text="Patient demographics and history"),
        PageText(number=2, text="6. VASCULAR STUDY\nThe great saphenous vein measures 5 mm."),
    ))
    fake = FakeLLM([{"facts": [{
        "field": "vein_diameter_mm", "value": 5, "unit": "mm",
        "state": "DOCUMENTED", "source_span": {"text": "measures 5 mm"},
        "confidence": 0.9,
    }]}])
    facts = extract_facts(document.text, ROOT, fake, document)
    span = facts["vein_diameter_mm"].source_span
    assert span.page == 2
    assert span.section == "6. VASCULAR STUDY"
    assert span.match_method == "exact"


def test_extract_facts_survives_null_facts_list():
    fake = FakeLLM([{"facts": None}])
    facts = extract_facts("chart text", ROOT, fake)
    assert facts["vein_diameter_mm"].found is False
    assert facts["saphenous_reflux_demonstrated"].found is False


def test_extract_facts_survives_malformed_entries():
    fake = FakeLLM([{"facts": [
        {"field": "vein_diameter_mm", "value": [1, 2, 3], "found": True},   # bad value type -> ValidationError
        {"value": 5, "found": True},                                        # missing "field" key
        "not even a dict",                                                  # junk entry
        {"field": "saphenous_reflux_demonstrated", "value": True, "found": True,
         "source_span": {"text": "reflux noted"}, "confidence": 0.9},       # one good fact
    ]}])
    facts = extract_facts("chart text", ROOT, fake)
    # good fact survives
    assert facts["saphenous_reflux_demonstrated"].value is True
    # malformed fact degrades to found=False instead of crashing
    assert facts["vein_diameter_mm"].found is False
