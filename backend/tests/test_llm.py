from app.llm import FakeLLM


def test_fake_llm_returns_queued_json():
    fake = FakeLLM([{"a": 1}, {"b": 2}])
    assert fake.complete_json("sys", "u1") == {"a": 1}
    assert fake.complete_json("sys", "u2") == {"b": 2}
    assert fake.calls[0]["user"] == "u1"
