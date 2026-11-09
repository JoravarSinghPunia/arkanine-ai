import re

from fastapi import FastAPI, Request

app = FastAPI(title="Arkanine fake inference server")

MODEL_ID = "fake-chat"


@app.get("/v1/models")
def list_models() -> dict[str, object]:
    return {"object": "list", "data": [{"id": MODEL_ID, "object": "model"}]}


@app.post("/v1/chat/completions")
async def chat_completions(request: Request) -> dict[str, object]:
    """Generate a canned response that references documents in the input."""
    body = await request.json()
    messages = body.get("messages", [])

    # Extract the user message
    user_message = ""
    for msg in messages:
        if msg.get("role") == "user":
            user_message = msg.get("content", "")
            break

    # Look for document references in the user message
    doc_refs = re.findall(r"\[Document (\d+)\]", user_message)

    # Generate a response that references the first document found
    if doc_refs:
        answer = f"Based on the information provided in [Document {doc_refs[0]}], the sky is blue."
    else:
        answer = "This is a canned answer from the fake inference server."

    return {
        "id": "chatcmpl-fake",
        "object": "chat.completion",
        "created": 0,
        "model": MODEL_ID,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": answer},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }
