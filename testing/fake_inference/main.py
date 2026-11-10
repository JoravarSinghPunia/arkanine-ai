"""A deterministic stand-in for an OpenAI-compatible inference server.

It behaves like a well-behaved model: it answers from the passage that shares the most
words with the question, cites it as [Pn], and replies NOT_FOUND when nothing matches.
Its embeddings are hashed bags of words, with a few synonyms folded together so tests can
tell retrieval by meaning apart from retrieval by shared words.
The last request to each endpoint is kept so tests can inspect exactly what was sent.
"""

import hashlib
import math
import re
from typing import Any

from fastapi import FastAPI, Request

app = FastAPI(title="Arkanine fake inference server")

CHAT_MODEL = "fake-chat"
EMBEDDING_MODEL = "fake-embed"
EMBEDDING_DIMENSIONS = 256
_PASSAGE = re.compile(r"^\[P(\d+)\][^\n]*\n(.*?)(?=\n\n\[P\d+\]|\n</passages>)", re.M | re.S)
_STOPWORDS = {"a", "an", "and", "are", "how", "is", "of", "the", "what", "which", "who", "why"}
# Keyed by stem, so "fixed" and "fixing" both mean "repair".
_SYNONYMS = {"car": "automobile", "fix": "repair"}

last_requests: dict[str, dict[str, Any]] = {"chat": {}, "embeddings": {}}


def _stem(word: str) -> str:
    """Crudely strip common English suffixes so "causes" matches "caused"."""
    for suffix in ("ing", "es", "ed", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[: -len(suffix)]
    return word


def _words(text: str) -> set[str]:
    words = set(re.findall(r"[a-z0-9]+", text.lower())) - _STOPWORDS
    return {_SYNONYMS.get(_stem(word), _stem(word)) for word in words}


def _answer(user_message: str) -> str:
    question = user_message.rsplit("Question:", 1)[-1]
    best_number, best_text, best_overlap = 0, "", 0
    for number, text in _PASSAGE.findall(user_message):
        overlap = len(_words(question) & _words(text))
        if overlap > best_overlap:
            best_number, best_text, best_overlap = int(number), text.strip(), overlap
    if not best_overlap:
        return "NOT_FOUND"
    return f"{best_text} [P{best_number}]"


def _embedding(text: str) -> list[float]:
    # The constant first component keeps every vector non-zero, as real models' are.
    vector = [0.0] * EMBEDDING_DIMENSIONS
    vector[0] = 0.1
    for word in _words(text):
        digest = hashlib.sha256(word.encode()).digest()
        vector[1 + int.from_bytes(digest[:4], "big") % (EMBEDDING_DIMENSIONS - 1)] += 1.0
    norm = math.sqrt(sum(value * value for value in vector))
    return [value / norm for value in vector]


async def _record(endpoint: str, request: Request) -> dict[str, Any]:
    body: dict[str, Any] = await request.json()
    last_requests[endpoint] = {**body, "_authorization": request.headers.get("authorization")}
    return body


@app.get("/v1/models")
def list_models() -> dict[str, object]:
    return {
        "object": "list",
        "data": [{"id": model, "object": "model"} for model in (CHAT_MODEL, EMBEDDING_MODEL)],
    }


@app.post("/v1/chat/completions")
async def chat_completions(request: Request) -> dict[str, object]:
    body = await _record("chat", request)
    user_message = next(
        (m.get("content", "") for m in body.get("messages", []) if m.get("role") == "user"), ""
    )
    return {
        "id": "chatcmpl-fake",
        "object": "chat.completion",
        "created": 0,
        "model": CHAT_MODEL,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": _answer(user_message)},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


@app.post("/v1/embeddings")
async def embeddings(request: Request) -> dict[str, object]:
    body = await _record("embeddings", request)
    inputs = body.get("input", [])
    texts = [inputs] if isinstance(inputs, str) else list(inputs)
    return {
        "object": "list",
        "data": [
            {"object": "embedding", "index": index, "embedding": _embedding(text)}
            for index, text in enumerate(texts)
        ],
        "model": EMBEDDING_MODEL,
        "usage": {"prompt_tokens": 0, "total_tokens": 0},
    }


@app.get("/_test/last_request")
def get_last_request() -> dict[str, Any]:
    """The last chat completion request, with its Authorization header as `_authorization`."""
    return last_requests["chat"]


@app.get("/_test/last_embedding_request")
def get_last_embedding_request() -> dict[str, Any]:
    """The last embeddings request, with its Authorization header as `_authorization`."""
    return last_requests["embeddings"]
