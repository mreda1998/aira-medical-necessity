import json
import logging
import os
from typing import Optional, Protocol

log = logging.getLogger("aira.llm")


class LLM(Protocol):
    def complete_json(self, system: str, user: str, *, model: Optional[str] = None) -> dict: ...


class OpenAILLM:
    def __init__(self, model: Optional[str] = None):
        from openai import OpenAI

        self._client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
        self._model = model or os.environ.get("PRIMARY_MODEL", "gpt-4o")
        # We prefer temperature=0 for deterministic extraction, but newer models
        # (gpt-5.x, o-series) reject any non-default temperature. Probe once on the
        # first call and remember the answer for the life of the client.
        self._send_temperature = True

    def complete_json(self, system: str, user: str, *, model: Optional[str] = None) -> dict:
        m = model or self._model
        kwargs = {
            "model": m,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "response_format": {"type": "json_object"},
        }
        if self._send_temperature:
            kwargs["temperature"] = 0

        log.debug("openai[%s] request (%d chars)", m, len(user))
        try:
            resp = self._client.chat.completions.create(**kwargs)
        except Exception as exc:  # noqa: BLE001 - inspected, then re-raised if unrelated
            msg = str(exc).lower()
            temperature_rejected = (
                self._send_temperature
                and "temperature" in msg
                and (getattr(exc, "status_code", None) == 400 or "support" in msg)
            )
            if not temperature_rejected:
                raise
            log.info("model %s rejects temperature=0; retrying with default temperature", m)
            self._send_temperature = False
            kwargs.pop("temperature", None)
            resp = self._client.chat.completions.create(**kwargs)

        content = resp.choices[0].message.content
        log.debug("openai[%s] response: %s", m, content)
        return json.loads(content)


class MistralLLM:
    def __init__(self, model: Optional[str] = None):
        from mistralai import Mistral

        self._client = Mistral(api_key=os.environ["MISTRAL_API_KEY"])
        self._model = model or os.environ.get("VERIFIER_MODEL", "mistral-large-latest")

    def complete_json(self, system: str, user: str, *, model: Optional[str] = None) -> dict:
        m = model or self._model
        log.debug("mistral[%s] request (%d chars)", m, len(user))
        resp = self._client.chat.complete(
            model=m,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            response_format={"type": "json_object"},
            temperature=0,
        )
        content = resp.choices[0].message.content
        log.debug("mistral[%s] response: %s", m, content)
        return json.loads(content)


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
