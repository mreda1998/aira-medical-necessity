import pytest
from fastapi.testclient import TestClient
from app.main import app, get_clients
from app.llm import FakeLLM


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


TREE_JSON = {"guideline_id": "g", "title": "t", "branches": [{
    "branch_id": "saphenous", "vein_types": ["great_saphenous"], "procedure_label": "saph",
    "root": {"kind": "leaf", "id": "reflux", "predicate": "boolean",
             "field": "saphenous_reflux_demonstrated", "threshold": True, "human_readable": "reflux"}}]}
ORDER_JSON = {"modality": "rfa", "vein": "great_saphenous", "laterality": "right", "cpt": "36475", "raw": "x"}
FACTS_JSON = {"facts": [{"field": "saphenous_reflux_demonstrated", "value": True, "found": True,
                         "source_span": {"text": "reflux"}, "confidence": 0.95}]}


def test_health():
    assert TestClient(app).get("/api/health").json() == {"status": "ok"}


def test_evaluate(monkeypatch, tmp_path):
    monkeypatch.setenv("CACHE_DIR", str(tmp_path))
    import importlib
    from app import store as app_store, compiler as app_compiler, pipeline as app_pipeline
    importlib.reload(app_store); importlib.reload(app_compiler); importlib.reload(app_pipeline)
    monkeypatch.setattr(app_pipeline, "extract_text", lambda b: "text")
    monkeypatch.setattr(app_compiler, "extract_text", lambda b: "text")
    app.dependency_overrides[get_clients] = lambda: (
        FakeLLM([TREE_JSON, ORDER_JSON, FACTS_JSON]), FakeLLM([]))
    client = TestClient(app)
    resp = client.post("/api/evaluate",
                       files={"guideline": ("g.pdf", b"g", "application/pdf"),
                              "chart": ("c.pdf", b"c", "application/pdf")})
    assert resp.status_code == 200
    assert resp.json()["evaluated_branches"][0]["verdict"] == "MET"


def test_evaluate_debug_returns_and_writes_trace(monkeypatch, tmp_path):
    monkeypatch.setenv("CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("DEBUG_DIR", str(tmp_path / "debug"))
    import importlib
    from app import store as app_store, compiler as app_compiler, pipeline as app_pipeline
    from app import main as app_main
    importlib.reload(app_store); importlib.reload(app_compiler); importlib.reload(app_pipeline)
    importlib.reload(app_main)
    monkeypatch.setattr(app_pipeline, "extract_text", lambda b: "text")
    monkeypatch.setattr(app_compiler, "extract_text", lambda b: "text")
    app_main.app.dependency_overrides[app_main.get_clients] = lambda: (
        FakeLLM([TREE_JSON, ORDER_JSON, FACTS_JSON]), FakeLLM([]))
    try:
        client = TestClient(app_main.app)
        resp = client.post(
            "/api/evaluate",
            data={"debug": "true"},
            files={"guideline": ("g.pdf", b"dbg-guideline", "application/pdf"),
                   "chart": ("c.pdf", b"dbg-chart", "application/pdf")},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["evaluated_branches"][0]["verdict"] == "MET"
        steps = {s["step"] for s in body["debug"]}
        assert {"guideline_tree", "order", "facts:saphenous", "verdict:saphenous"} <= steps
        # per-step JSON files were written to DEBUG_DIR
        written = list((tmp_path / "debug").rglob("*.json"))
        assert any("guideline_tree" in p.name for p in written)
    finally:
        app_main.app.dependency_overrides.clear()
        importlib.reload(app_store); importlib.reload(app_compiler)
        importlib.reload(app_pipeline); importlib.reload(app_main)


def test_evaluate_invalid_tree_returns_502(monkeypatch, tmp_path):
    monkeypatch.setenv("CACHE_DIR", str(tmp_path))
    import importlib
    from app import store as app_store, compiler as app_compiler, pipeline as app_pipeline
    importlib.reload(app_store); importlib.reload(app_compiler); importlib.reload(app_pipeline)
    monkeypatch.setattr(app_pipeline, "extract_text", lambda b: "text")
    monkeypatch.setattr(app_compiler, "extract_text", lambda b: "text")
    app.dependency_overrides[get_clients] = lambda: (
        FakeLLM([{"nonsense": True}]), FakeLLM([]))
    client = TestClient(app)
    resp = client.post("/api/evaluate",
                       files={"guideline": ("g.pdf", b"g", "application/pdf"),
                              "chart": ("c.pdf", b"c", "application/pdf")})
    assert resp.status_code == 502


def test_evaluate_llm_malformed_json_returns_502(monkeypatch, tmp_path):
    monkeypatch.setenv("CACHE_DIR", str(tmp_path))
    import importlib
    from app import store as app_store, compiler as app_compiler, pipeline as app_pipeline
    importlib.reload(app_store); importlib.reload(app_compiler); importlib.reload(app_pipeline)
    monkeypatch.setattr(app_pipeline, "extract_text", lambda b: "text")
    monkeypatch.setattr(app_compiler, "extract_text", lambda b: "text")

    class BrokenLLM:
        def complete_json(self, system, user, *, model=None):
            import json as _json
            raise _json.JSONDecodeError("Expecting value", "garbage", 0)

    app.dependency_overrides[get_clients] = lambda: (BrokenLLM(), BrokenLLM())
    client = TestClient(app)
    resp = client.post("/api/evaluate",
                       files={"guideline": ("g2.pdf", b"unique-guideline-bytes", "application/pdf"),
                              "chart": ("c2.pdf", b"unique-chart-bytes", "application/pdf")})
    assert resp.status_code == 502
    assert "malformed JSON" in resp.json()["detail"]


def test_evaluate_unexpected_exception_returns_502_pipeline_failure(monkeypatch, tmp_path):
    monkeypatch.setenv("CACHE_DIR", str(tmp_path))
    import importlib
    from app import store as app_store, compiler as app_compiler, pipeline as app_pipeline
    importlib.reload(app_store); importlib.reload(app_compiler); importlib.reload(app_pipeline)
    monkeypatch.setattr(app_pipeline, "extract_text", lambda b: "text")
    monkeypatch.setattr(app_compiler, "extract_text", lambda b: "text")

    class ExplodingLLM:
        def complete_json(self, system, user, *, model=None):
            raise TypeError("unexpected LLM client shape")

    app.dependency_overrides[get_clients] = lambda: (ExplodingLLM(), ExplodingLLM())
    client = TestClient(app)
    resp = client.post("/api/evaluate",
                       files={"guideline": ("g3.pdf", b"unique-guideline-bytes-3", "application/pdf"),
                              "chart": ("c3.pdf", b"unique-chart-bytes-3", "application/pdf")})
    assert resp.status_code == 502
    assert "pipeline failure" in resp.json()["detail"]
    assert "TypeError" in resp.json()["detail"]
