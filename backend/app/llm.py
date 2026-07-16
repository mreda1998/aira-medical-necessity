import json
import os
from typing import Optional, Protocol


class LLM(Protocol):
    def complete_json(self, system: str, user: str, *, model: Optional[str] = None) -> dict: ...


class OpenAILLM:
    def __init__(self, model: Optional[str] = None):
        from openai import OpenAI
        self._client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
        self._model = model or os.environ.get("PRIMARY_MODEL", "gpt-4o")

    def complete_json(self, system: str, user: str, *, model: Optional[str] = None) -> dict:
        resp = self._client.chat.completions.create(
            model=model or self._model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            response_format={"type": "json_object"},
            temperature=0,
        )
        return json.loads(resp.choices[0].message.content)


class MistralLLM:
    def __init__(self, model: Optional[str] = None):
        from mistralai import Mistral
        self._client = Mistral(api_key=os.environ["MISTRAL_API_KEY"])
        self._model = model or os.environ.get("VERIFIER_MODEL", "mistral-large-latest")

    def complete_json(self, system: str, user: str, *, model: Optional[str] = None) -> dict:
        resp = self._client.chat.complete(
            model=model or self._model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            response_format={"type": "json_object"},
            temperature=0,
        )
        return json.loads(resp.choices[0].message.content)


class FakeLLM:
    """Test double: returns queued dicts in order, records calls."""

    def __init__(self, responses: list[dict]):
        self._responses = list(responses)
        self.calls: list[dict] = []

    def complete_json(self, system: str, user: str, *, model: Optional[str] = None) -> dict:
        self.calls.append({"system": system, "user": user, "model": model})
        return self._responses.pop(0)


def openai_client() -> OpenAILLM:
    return OpenAILLM()


def mistral_client() -> MistralLLM:
    return MistralLLM()
