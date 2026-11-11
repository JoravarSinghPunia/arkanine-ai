"""The one OpenAI-compatible interface every model call goes through.

Ollama, llama.cpp's server and vLLM all speak this protocol, so switching backend is a
matter of configuration. Chat and embeddings are configured separately because llama.cpp
and vLLM serve one model per server.
"""

import os
from dataclasses import dataclass
from typing import Literal, Optional

import httpx

CHECK_TIMEOUT_SECONDS = 2
INFERENCE_TIMEOUT_SECONDS = 120
EMBEDDING_BATCH_SIZE = 64

EmbeddingPurpose = Literal["query", "document"]


class NotConfigured(Exception):
    """No model is configured for this kind of call."""


class InferenceFailed(Exception):
    """The inference server could not be reached or gave an unusable reply."""


@dataclass(frozen=True)
class Endpoint:
    base_url: str
    model: Optional[str]
    api_key: Optional[str]

    def post(self, path: str, body: dict[str, object]) -> object:
        if not self.base_url or not self.model:
            raise NotConfigured
        try:
            response = httpx.post(
                f"{self.base_url}{path}",
                json={"model": self.model, **body},
                headers=self._headers(),
                timeout=INFERENCE_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise InferenceFailed from error

    def check(self) -> str:
        if not self.base_url:
            return "unavailable"
        try:
            httpx.get(
                f"{self.base_url}/models", headers=self._headers(), timeout=CHECK_TIMEOUT_SECONDS
            ).raise_for_status()
        except httpx.HTTPError:
            return "unavailable"
        return "ok"

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}


def _env(name: str, default: Optional[str] = None) -> Optional[str]:
    return os.environ.get(name) or default


def chat_endpoint() -> Endpoint:
    return Endpoint(
        base_url=(_env("INFERENCE_BASE_URL") or "").rstrip("/"),
        model=_env("INFERENCE_MODEL"),
        api_key=_env("INFERENCE_API_KEY"),
    )


def embedding_endpoint() -> Endpoint:
    chat = chat_endpoint()
    return Endpoint(
        base_url=(_env("EMBEDDING_BASE_URL") or chat.base_url).rstrip("/"),
        model=_env("EMBEDDING_MODEL"),
        api_key=_env("EMBEDDING_API_KEY", chat.api_key),
    )


def embedding_model() -> str:
    model = embedding_endpoint().model
    if not model:
        raise NotConfigured
    return model


def complete(messages: list[dict[str, str]]) -> str:
    """Ask for a chat completion. The model is never offered tools."""
    reply = chat_endpoint().post("/chat/completions", {"messages": messages})
    try:
        return str(reply["choices"][0]["message"]["content"])  # type: ignore[index]
    except (KeyError, IndexError, TypeError) as error:
        raise InferenceFailed from error


def embed(texts: list[str], purpose: EmbeddingPurpose) -> list[list[float]]:
    """Embed texts in order. Some models (e.g. nomic-embed-text) need a prefix per purpose."""
    endpoint = embedding_endpoint()
    prefix = _env(f"EMBEDDING_{purpose.upper()}_PREFIX", "") or ""
    vectors: list[list[float]] = []
    for start in range(0, len(texts), EMBEDDING_BATCH_SIZE):
        batch = [prefix + text for text in texts[start : start + EMBEDDING_BATCH_SIZE]]
        reply = endpoint.post("/embeddings", {"input": batch})
        try:
            data = sorted(reply["data"], key=lambda item: item["index"])  # type: ignore[index]
            vectors.extend([float(value) for value in item["embedding"]] for item in data)
        except (KeyError, TypeError, ValueError) as error:
            raise InferenceFailed from error
        if len(vectors) != min(start + EMBEDDING_BATCH_SIZE, len(texts)):
            raise InferenceFailed
    return vectors
