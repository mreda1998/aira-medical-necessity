from app.llm import FakeLLM
from app.compiler import (
    COMPILER_SYSTEM,
    _enrich_source_spans,
    compile_guideline,
    criteria_fidelity_issues,
)
from app.models import CriteriaTree
from app.pdf_extract import ExtractedDocument, PageText

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


def test_guideline_quotes_are_resolved_to_policy_pages():
    raw = {
        **TREE_JSON,
        "branches": [{
            **TREE_JSON["branches"][0],
            "root": {
                "kind": "leaf", "id": "bmi", "predicate": "numeric_gte",
                "field": "bmi", "threshold": 35, "human_readable": "BMI at least 35",
                "source_span": {"text": "BMI (Body Mass Index) ≥35 kg/m2"},
            },
        }],
    }
    tree = CriteriaTree.model_validate(raw)
    document = ExtractedDocument(pages=(
        PageText(number=1, text="Table of Contents"),
        PageText(
            number=2,
            text="COVERAGE POLICY\nBMI (Body Mass Index) ≥35 kg/m2 qualifies.",
        ),
    ))
    enriched = _enrich_source_spans(tree, document)
    span = enriched.branches[0].root.source_span
    assert span.page == 2
    assert span.section == "COVERAGE POLICY"
    assert span.match_method == "exact"


def test_compiler_retries_when_a_range_and_comorbidity_are_collapsed():
    bad = {
        "guideline_id": "0051", "title": "Bariatric", "branches": [{
            "branch_id": "adult", "procedure_label": "Bariatric surgery",
            "root": {"kind": "leaf", "id": "bmi", "predicate": "numeric_gte",
                     "field": "bmi", "threshold": 30,
                     "human_readable": "BMI 30-34.9 with at least one comorbidity"},
        }],
    }
    repaired = {
        "guideline_id": "0051", "title": "Bariatric", "branches": [{
            "branch_id": "adult", "procedure_label": "Bariatric surgery",
            "root": {"kind": "all_of", "id": "lower_bmi", "children": [
                {"kind": "leaf", "id": "bmi_min", "predicate": "numeric_gte",
                 "field": "bmi", "threshold": 30, "human_readable": "BMI at least 30",
                 "source_span": {"text": "BMI 30-34.9 with at least one comorbidity"}},
                {"kind": "leaf", "id": "bmi_max", "predicate": "numeric_lte",
                 "field": "bmi", "threshold": 34.9, "human_readable": "BMI at most 34.9",
                 "source_span": {"text": "BMI 30-34.9 with at least one comorbidity"}},
                {"kind": "n_of", "id": "comorbidities", "k": 1, "children": [
                    {"kind": "leaf", "id": "diabetes", "predicate": "existence",
                     "field": "diabetes", "human_readable": "Diabetes"},
                ]},
            ]},
        }],
    }
    fake = FakeLLM([bad, repaired])
    tree = compile_guideline("BMI policy", fake)
    assert len(fake.calls) == 2
    assert criteria_fidelity_issues(tree) == []
    assert "failed deterministic fidelity checks" in fake.calls[1]["user"]
    assert "GUIDELINE TEXT" not in fake.calls[1]["user"]


def test_complete_compound_quote_does_not_invalidate_atomic_nested_leaves():
    quote = "BMI 30-34.9 with at least one clinically significant comorbidity"
    tree = CriteriaTree.model_validate({
        "guideline_id": "0051", "title": "Bariatric", "branches": [{
            "branch_id": "adult", "procedure_label": "Bariatric surgery",
            "root": {"kind": "all_of", "id": "lower_bmi_path", "children": [
                {"kind": "all_of", "id": "bmi_bounds", "children": [
                    {"kind": "leaf", "id": "bmi_min", "predicate": "numeric_gte",
                     "field": "bmi", "threshold": 30, "human_readable": "BMI at least 30",
                     "source_span": {"text": quote}},
                    {"kind": "leaf", "id": "bmi_max", "predicate": "numeric_lte",
                     "field": "bmi", "threshold": 34.9, "human_readable": "BMI at most 34.9",
                     "source_span": {"text": quote}},
                ]},
                {"kind": "n_of", "id": "comorbidities", "k": 1, "children": [
                    {"kind": "leaf", "id": "diabetes", "predicate": "existence",
                     "field": "diabetes", "human_readable": "Type 2 diabetes",
                     "source_span": {"text": quote}},
                ]},
            ]},
        }],
    })
    assert criteria_fidelity_issues(tree) == []


def test_compiler_flags_double_negation_upper_bound_and_collapsed_absences():
    tree = CriteriaTree.model_validate({
        "guideline_id": "g", "title": "Stroke", "branches": [{
            "branch_id": "thrombectomy", "procedure_label": "Mechanical thrombectomy",
            "root": {"kind": "all_of", "id": "root", "children": [
                {"kind": "leaf", "id": "timing", "predicate": "duration_gte",
                 "field": "symptom_onset_hours", "threshold": 12, "unit": "hours",
                 "negated": True, "human_readable": "Within 12 hours of symptom onset"},
                {"kind": "leaf", "id": "imaging", "predicate": "boolean",
                 "field": "intracranial_hemorrhage", "threshold": False,
                 "negated": True,
                 "human_readable": "No evidence of intracranial hemorrhage or arterial dissection"},
            ]},
        }],
    })
    issues = criteria_fidelity_issues(tree)
    assert any("upper-bounded timing" in issue for issue in issues)
    assert any("double-negates" in issue for issue in issues)
    assert any("absence of alternatives" in issue for issue in issues)


def test_compiler_retries_schema_invalid_node_kind():
    malformed = {
        "guideline_id": "g", "title": "Policy", "branches": [{
            "branch_id": "adult", "procedure_label": "Procedure",
            "root": {"kind": "numeric_gt", "id": "age", "field": "age",
                     "threshold": 18, "human_readable": "Age greater than 18"},
        }],
    }
    repaired = {
        "guideline_id": "g", "title": "Policy", "branches": [{
            "branch_id": "adult", "procedure_label": "Procedure",
            "root": {"kind": "leaf", "id": "age", "predicate": "numeric_gt",
                     "field": "age", "threshold": 18,
                     "human_readable": "Age greater than 18"},
        }],
    }
    fake = FakeLLM([malformed, repaired])
    tree = compile_guideline("Age policy", fake)
    assert tree.branches[0].root.kind == "leaf"
    assert len(fake.calls) == 2
    assert "violated the required JSON schema" in fake.calls[1]["user"]


def test_compiler_flags_duration_hidden_in_existence_leaf():
    tree = CriteriaTree.model_validate({
        "guideline_id": "g", "title": "OSA", "branches": [{
            "branch_id": "uppp", "procedure_label": "UPPP",
            "root": {"kind": "leaf", "id": "cpap", "predicate": "existence",
                     "field": "cpap_intolerance",
                     "human_readable": "CPAP intolerance despite adjustments over at least 1 month"},
        }],
    })
    assert any("duration" in issue for issue in criteria_fidelity_issues(tree))


def test_compile_cached_recompiles_when_prompt_changes(tmp_path, monkeypatch):
    # The disk cache used to be keyed on PDF content alone, so a prompt fix
    # (like the ANDed-clause-splitting rule) would never reach guidelines
    # that were already cached under the old prompt. compile_cached must fold
    # COMPILER_SYSTEM into the cache key so a prompt change busts the cache.
    import app.store, app.compiler, importlib
    monkeypatch.setenv("CACHE_DIR", str(tmp_path))
    importlib.reload(app.store)
    importlib.reload(app.compiler)
    monkeypatch.setattr(app.compiler, "extract_text", lambda b: "guideline text")
    try:
        fake = FakeLLM([TREE_JSON, TREE_JSON])
        data = b"same-pdf-bytes"

        app.compiler.compile_cached(data, fake)
        assert len(fake.calls) == 1

        # same bytes, same prompt -> cache hit, no new LLM call
        app.compiler.compile_cached(data, fake)
        assert len(fake.calls) == 1

        # prompt changes -> cache key changes -> recompiles (2nd LLM call)
        monkeypatch.setattr(app.compiler, "COMPILER_SYSTEM", "a different system prompt")
        app.compiler.compile_cached(data, fake)
        assert len(fake.calls) == 2
    finally:
        monkeypatch.undo()
        importlib.reload(app.store)
        importlib.reload(app.compiler)
