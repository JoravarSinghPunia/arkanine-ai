from collections.abc import Callable

import httpx


def test_answers_find_passages_by_meaning_not_only_shared_words(
    api: httpx.Client, collection_id: int, ingest: Callable[[str, str], int]
) -> None:
    # The fake model treats car/automobile and fixed/repaired as the same meaning.
    ingest("Fleet log", "The automobile was repaired on Tuesday.\n\nThe office cat sleeps all day.")

    answer = api.post(
        f"/collections/{collection_id}/answer", json={"question": "When was the car fixed?"}
    ).json()

    assert answer["answered"] is True
    assert [c["text"] for c in answer["citations"]] == ["The automobile was repaired on Tuesday."]


def test_model_calls_use_the_configured_models_and_api_key(
    api: httpx.Client,
    fake_inference: httpx.Client,
    collection_id: int,
    ingest: Callable[[str, str], int],
    inference_api_key: str,
) -> None:
    ingest("Nature facts", "The sky is blue.")

    api.post(f"/collections/{collection_id}/answer", json={"question": "What colour is the sky?"})
    chat = fake_inference.get("/_test/last_request").json()
    embeddings = fake_inference.get("/_test/last_embedding_request").json()

    assert chat["model"] == "fake-chat"
    assert embeddings["model"] == "fake-embed"
    assert embeddings["input"] == ["What colour is the sky?"]
    assert chat["_authorization"] == f"Bearer {inference_api_key}"
    assert embeddings["_authorization"] == f"Bearer {inference_api_key}"
