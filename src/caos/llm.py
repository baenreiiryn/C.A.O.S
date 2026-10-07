from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Protocol


class LLMError(RuntimeError):
    pass


class LocalLLM(Protocol):
    def complete(self, system: str, user: str) -> str: ...


def _post_json(url: str, payload: dict, timeout: float = 120.0) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise LLMError(str(exc)) from exc


@dataclass(slots=True)
class OllamaClient:
    model: str
    base_url: str = "http://127.0.0.1:11434"
    temperature: float = 0.1

    def complete(self, system: str, user: str) -> str:
        payload = {
            "model": self.model,
            "stream": False,
            "options": {"temperature": self.temperature},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        result = _post_json(self.base_url.rstrip("/") + "/api/chat", payload)
        try:
            return str(result["message"]["content"])
        except (KeyError, TypeError) as exc:
            raise LLMError(f"unexpected Ollama response: {result}") from exc


@dataclass(slots=True)
class OpenAICompatClient:
    model: str
    base_url: str = "http://127.0.0.1:1234/v1"
    api_key: str = "local"
    temperature: float = 0.1

    def complete(self, system: str, user: str) -> str:
        url = self.base_url.rstrip("/") + "/chat/completions"
        payload = {
            "model": self.model,
            "temperature": self.temperature,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=120.0) as resp:
                result = json.loads(resp.read().decode("utf-8"))
            return str(result["choices"][0]["message"]["content"])
        except Exception as exc:
            raise LLMError(str(exc)) from exc


@dataclass(slots=True)
class StaticLLM:
    """Deterministic offline LLM substitute used by tests and smoke demos."""

    response: str

    def complete(self, system: str, user: str) -> str:
        return self.response
