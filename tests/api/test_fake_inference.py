import httpx

CHAT_REQUEST = {"model": "fake-chat", "messages": [{"role": "user", "content": "hello"}]}


def test_lists_models(fake_inference: httpx.Client) -> None:
    body = fake_inference.get("/v1/models").json()

    assert [m["id"] for m in body["data"]] == ["fake-chat"]


def test_chat_completion_is_deterministic(fake_inference: httpx.Client) -> None:
    first = fake_inference.post("/v1/chat/completions", json=CHAT_REQUEST).json()
    second = fake_inference.post("/v1/chat/completions", json=CHAT_REQUEST).json()

    assert first == second
    assert first["choices"][0]["message"]["role"] == "assistant"
