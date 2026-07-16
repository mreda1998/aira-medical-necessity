import types

import pytest

from app.llm import FakeLLM, OpenAILLM


def test_fake_llm_returns_queued_json():
    fake = FakeLLM([{"a": 1}, {"b": 2}])
    assert fake.complete_json("sys", "u1") == {"a": 1}
    assert fake.complete_json("sys", "u2") == {"b": 2}
    assert fake.calls[0]["user"] == "u1"


class _StubCompletions:
    """Records kwargs; optionally rejects temperature=0 the way gpt-5.x does."""

    def __init__(self, reject_temperature: bool, error: Exception | None = None):
        self.calls: list[dict] = []
        self.reject_temperature = reject_temperature
        self.error = error

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        if self.reject_temperature and "temperature" in kwargs:
            err = Exception("Unsupported value: 'temperature' does not support 0 with this model")
            err.status_code = 400  # type: ignore[attr-defined]
            raise err
        msg = types.SimpleNamespace(content='{"ok": true}')
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=msg)])


def _make_llm(monkeypatch, stub_completions, model="gpt-4o"):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    llm = OpenAILLM(model=model)
    llm._client = types.SimpleNamespace(
        chat=types.SimpleNamespace(completions=stub_completions)
    )
    return llm


def test_openai_retries_without_temperature_when_model_rejects_it(monkeypatch):
    stub = _StubCompletions(reject_temperature=True)
    llm = _make_llm(monkeypatch, stub, model="gpt-5.6")

    assert llm.complete_json("sys", "user") == {"ok": True}
    # first attempt sent temperature (rejected), retry omitted it
    assert "temperature" in stub.calls[0]
    assert "temperature" not in stub.calls[1]
    assert llm._send_temperature is False

    # subsequent calls skip the probe entirely — no wasted rejected call
    llm.complete_json("sys", "user2")
    assert "temperature" not in stub.calls[2]
    assert len(stub.calls) == 3


def test_openai_keeps_temperature_when_model_supports_it(monkeypatch):
    stub = _StubCompletions(reject_temperature=False)
    llm = _make_llm(monkeypatch, stub, model="gpt-4o")

    assert llm.complete_json("sys", "user") == {"ok": True}
    assert "temperature" in stub.calls[0]
    assert stub.calls[0]["temperature"] == 0
    assert llm._send_temperature is True
    assert len(stub.calls) == 1  # no retry


def test_openai_reraises_unrelated_errors(monkeypatch):
    boom = Exception("rate limit exceeded")
    boom.status_code = 429  # type: ignore[attr-defined]
    stub = _StubCompletions(reject_temperature=False, error=boom)
    llm = _make_llm(monkeypatch, stub)

    with pytest.raises(Exception, match="rate limit"):
        llm.complete_json("sys", "user")
    assert len(stub.calls) == 1  # not retried
