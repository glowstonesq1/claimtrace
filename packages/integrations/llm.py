"""LLM providers. One seam, three adapters: none (rules), OpenAI-compatible HTTP, and a fake for tests.

The OpenAI-compatible adapter covers OpenAI, Ollama (/v1), vLLM, LM Studio and llama.cpp server.
Providers have no tools and cannot take actions; they only return text that callers validate.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Protocol

import httpx

from claimtrace.core.config import Settings


class LLMError(Exception):
    pass


class LLMProvider(Protocol):
    name: str
    model: str
    host: str | None
    external: bool

    def complete_json(self, system: str, user: str) -> dict: ...


class OpenAICompatible:
    name = "openai"

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str | None,
        external: bool,
        host: str | None,
        timeout: float = 120.0,
        retries: int = 2,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.external = external
        self.host = host
        self._key = api_key
        self._timeout = timeout
        self._retries = retries
        self._transport = transport

    def complete_json(self, system: str, user: str) -> dict:
        body = {
            "model": self.model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }
        headers = {"Authorization": f"Bearer {self._key}"} if self._key else {}
        last: Exception | None = None
        for attempt in range(self._retries + 1):
            try:
                with httpx.Client(timeout=self._timeout, transport=self._transport) as client:
                    r = client.post(f"{self.base_url}/chat/completions", json=body, headers=headers)
                if r.status_code in (429, 500, 502, 503, 504):
                    raise LLMError(f"provider returned {r.status_code}")
                if r.status_code != 200:
                    raise LLMError(f"provider returned {r.status_code}")  # never echo body: may contain input
                content = r.json()["choices"][0]["message"]["content"]
                return _loads_object(content)
            except (httpx.HTTPError, LLMError, KeyError, ValueError) as e:
                last = e
                if attempt < self._retries:
                    time.sleep(min(2**attempt, 8))
        raise LLMError(f"LLM call failed after retries: {type(last).__name__}")


class FakeProvider:
    """Deterministic provider for tests: `responder(system, user) -> dict`."""

    name = "fake"

    def __init__(self, responder: Callable[[str, str], dict], external: bool = False) -> None:
        self.model = "fake-model"
        self.host = "fake.invalid" if external else "localhost"
        self.external = external
        self.responder = responder
        self.calls: list[tuple[str, str]] = []

    def complete_json(self, system: str, user: str) -> dict:
        self.calls.append((system, user))
        return self.responder(system, user)


def _loads_object(content: str) -> dict:
    content = content.strip()
    if content.startswith("```"):
        content = content.strip("`").split("\n", 1)[-1]
    start, end = content.find("{"), content.rfind("}")
    if start < 0 or end < 0:
        raise ValueError("no JSON object")
    obj = json.loads(content[start : end + 1])
    if not isinstance(obj, dict):
        raise ValueError("not an object")
    return obj


def provider_from_settings(s: Settings) -> LLMProvider | None:
    if s.llm_provider in ("", "rules", "none"):
        return None
    if s.llm_provider in ("openai", "ollama", "openai-compatible"):
        base = s.llm_base_url or ("http://localhost:11434/v1" if s.llm_provider == "ollama" else None)
        if not base or not s.llm_model:
            raise LLMError("Set CLAIMTRACE_LLM_BASE_URL and CLAIMTRACE_LLM_MODEL to use an LLM provider.")
        from urllib.parse import urlsplit

        host = urlsplit(base).hostname
        external = bool(host) and host not in ("localhost", "127.0.0.1", "::1", "ollama", "host.docker.internal")
        return OpenAICompatible(base, s.llm_model, s.llm_api_key, external=external, host=host)
    raise LLMError(f"Unknown LLM provider '{s.llm_provider}'.")
