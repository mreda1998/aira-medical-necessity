from app.llm import FakeLLM
from app.models import Status
from app.pdf_extract import ExtractedDocument, PageText
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


def _fake_document(_data: bytes) -> ExtractedDocument:
    return ExtractedDocument(pages=(
        PageText(number=1, text="RFA right GSV. Reflux present. The vein measures 5 mm."),
    ))


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
    monkeypatch.setattr(app.pipeline, "extract_document", _fake_document)
    monkeypatch.setattr(app.compiler, "extract_text", lambda b: "text")
    try:
        primary = FakeLLM([TREE_JSON, ORDER_JSON, FACTS_JSON])
        verifier = FakeLLM([])
        progress = []
        result = app.pipeline.run(b"g", b"c", primary, verifier, progress=progress.append)
        assert result.evaluated_branches[0].verdict == Status.MET
        assert result.chart_document.page_count == 1
        assert result.evaluated_branches[0].decisive_findings[0].evidence.source_span.page == 1
        assert [f.node_id for f in result.evaluated_branches[0].decisive_findings] == [
            "reflux", "size"
        ]
        # no tracer passed -> no debug payload
        assert result.debug is None
        stages = [update.stage for update in progress]
        assert stages[0] == "document_preflight"
        assert "guideline_compilation" in stages
        assert "branch_extraction" in stages
        assert stages[-1] == "complete"

        # with a tracer, every pipeline step is captured for debugging
        from app.trace import Tracer

        tracer = Tracer()
        primary2 = FakeLLM([ORDER_JSON, FACTS_JSON])  # guideline now cached, no recompile
        result2 = app.pipeline.run(b"g", b"c", primary2, FakeLLM([]), tracer)
        steps = {s["step"] for s in result2.debug}
        assert "document_preflight" in steps
        assert "guideline_tree" in steps
        assert "order" in steps
        assert "facts:saphenous" in steps
        assert "verdict:saphenous" in steps
        # the captured verdict matches the returned one, and is JSON-serializable
        import json

        json.dumps(result2.debug)
        verdict_step = next(s for s in result2.debug if s["step"] == "verdict:saphenous")
        assert verdict_step["data"]["verdict"] == "MET"

        # A procedure unrelated to the cached policy stops at routing. No fact
        # extraction response is queued, so evaluating a branch would fail.
        mismatch = {
            "modality": "Permanent cardiac pacemaker implantation",
            "cpt": "33207",
            "raw": "Permanent pacemaker CPT 33207",
        }
        mismatch_primary = FakeLLM([mismatch])
        mismatch_result = app.pipeline.run(b"g", b"c", mismatch_primary, FakeLLM([]))
        assert mismatch_result.route_flag == "policy_not_applicable"
        assert mismatch_result.evaluated_branches == []
        assert len(mismatch_primary.calls) == 1
    finally:
        monkeypatch.undo()
        importlib.reload(app.store)
        importlib.reload(app.compiler)
        importlib.reload(app.pipeline)
