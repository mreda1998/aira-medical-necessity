from app.llm import FakeLLM
from app.compiler import compile_guideline, COMPILER_SYSTEM, criteria_fidelity_issues
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
                 "field": "bmi", "threshold": 30, "human_readable": "BMI at least 30"},
                {"kind": "leaf", "id": "bmi_max", "predicate": "numeric_lte",
                 "field": "bmi", "threshold": 34.9, "human_readable": "BMI at most 34.9"},
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
