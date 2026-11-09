"""A deterministic stand-in for an OpenAI-compatible inference server.

It behaves like a well-behaved model: it answers from the passage that shares the most
words with the question, cites it as [Pn], and replies NOT_FOUND when nothing matches.
The last chat request is kept so tests can inspect exactly what the model was sent.
"""

import re
from typing import Any

from fastapi import FastAPI, Request

app = FastAPI(title="Arkanine fake inference server")

MODEL_ID = "fake-chat"
_PASSAGE = re.compile(r"^\[P(\d+)\][^\n]*\n(.*?)(?=\n\n\[P\d+\]|\n</passages>)", re.M | re.S)
_STOPWORDS = {"a", "an", "and", "are", "how", "is", "of", "the", "what", "which", "who", "why"}

last_request: dict[str, Any] = {}


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower())) - _STOPWORDS


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


@app.get("/v1/models")
def list_models() -> dict[str, object]:
    return {"object": "list", "data": [{"id": MODEL_ID, "object": "model"}]}


@app.post("/v1/chat/completions")
async def chat_completions(request: Request) -> dict[str, object]:
    body = await request.json()
    last_request.clear()
    last_request.update(body)
    user_message = next(
        (m.get("content", "") for m in body.get("messages", []) if m.get("role") == "user"), ""
    )
    return {
        "id": "chatcmpl-fake",
        "object": "chat.completion",
        "created": 0,
        "model": MODEL_ID,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": _answer(user_message)},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


@app.get("/_test/last_request")
def get_last_request() -> dict[str, Any]:
    return last_request
