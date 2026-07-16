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
