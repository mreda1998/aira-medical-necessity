from app.llm import FakeLLM
from app.models import Status
from pathlib import Path

SAMPLES = Path(__file__).parent / "samples"

# Compiled tree the primary LLM will "return" for the guideline.
TREE_JSON = {
    "guideline_id": "02-33000-31", "title": "Varicose Veins", "branches": [{
        "branch_id": "saphenous", "vein_types": ["great_saphenous"], "procedure_label": "saph",
        "root": {"kind": "all_of", "id": "root", "children": [
            {"kind": "leaf", "id": "reflux", "predicate": "boolean",
             "field": "saphenous_reflux_demonstrated", "threshold": True, "human_readable": "reflux"},
            {"kind": "leaf", "id": "size", "predicate": "numeric_gte", "field": "vein_diameter_mm",
             "threshold": 3, "unit": "mm", "human_readable": "size"},
        ]}}]}
ORDER_JSON = {"modality": "radiofrequency", "vein": "great_saphenous", "laterality": "right",
              "cpt": "36475", "raw": "RFA right GSV"}
FACTS_JSON = {"facts": [
    {"field": "saphenous_reflux_demonstrated", "value": True, "found": True,
     "source_span": {"text": "reflux present"}, "confidence": 0.95},
    {"field": "vein_diameter_mm", "value": 5, "unit": "mm", "found": True,
     "source_span": {"text": "5 mm"}, "confidence": 0.95},
]}


def test_run_end_to_end_with_fakes(tmp_path, monkeypatch):
    # NOTE: importlib.reload() mutates the module object *in place*, so
    # app.compiler's `from . import store` reference also picks up the
    # patched CACHE_DIR. monkeypatch.setenv/setattr auto-revert at teardown,
    # but that alone would leave app.store/app.compiler/app.pipeline reloaded
    # with the tmp_path-scoped CACHE_DIR baked in for the rest of the test
    # session. Explicitly undo + reload again in `finally` so later tests
    # see the original module state.
    import app.store, app.compiler, app.pipeline, importlib
    monkeypatch.setenv("CACHE_DIR", str(tmp_path))
    importlib.reload(app.store)
    importlib.reload(app.compiler)
    importlib.reload(app.pipeline)
    monkeypatch.setattr(app.pipeline, "extract_text", lambda b: "text")
    monkeypatch.setattr(app.compiler, "extract_text", lambda b: "text")
    try:
        primary = FakeLLM([TREE_JSON, ORDER_JSON, FACTS_JSON])
        verifier = FakeLLM([])
        result = app.pipeline.run(b"g", b"c", primary, verifier)
        assert result.evaluated_branches[0].verdict == Status.MET
        # no tracer passed -> no debug payload
        assert result.debug is None

        # with a tracer, every pipeline step is captured for debugging
        from app.trace import Tracer

        tracer = Tracer()
        primary2 = FakeLLM([ORDER_JSON, FACTS_JSON])  # guideline now cached, no recompile
        result2 = app.pipeline.run(b"g", b"c", primary2, FakeLLM([]), tracer)
        steps = {s["step"] for s in result2.debug}
        assert "guideline_tree" in steps
        assert "order" in steps
        assert "facts:saphenous" in steps
        assert "verdict:saphenous" in steps
        # the captured verdict matches the returned one, and is JSON-serializable
        import json

        json.dumps(result2.debug)
        verdict_step = next(s for s in result2.debug if s["step"] == "verdict:saphenous")
        assert verdict_step["data"]["verdict"] == "MET"
    finally:
        monkeypatch.undo()
        importlib.reload(app.store)
        importlib.reload(app.compiler)
        importlib.reload(app.pipeline)
