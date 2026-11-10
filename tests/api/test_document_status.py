"""The document list of a Collection, with each document's ingestion status."""

import httpx


def test_lists_ingested_and_rejected_documents_with_their_status(
    api: httpx.Client, collection_id: int
) -> None:
    documents = f"/collections/{collection_id}/documents"
    ingested = api.post(documents, json={"title": "Notes", "content": "The sky is blue."})
    rejected = api.post(f"{documents}/upload", files={"file": ("budget.xlsx", b"PK")})

    listed = api.get(documents)

    assert rejected.status_code == 415
    assert listed.status_code == 200
    assert [(d["title"], d["status"]) for d in listed.json()] == [
        ("Notes", "ready"),
        ("budget.xlsx", "failed"),
    ]
    assert listed.json()[0]["id"] == ingested.json()["id"]
    assert listed.json()[0]["error"] is None
    assert "spreadsheets are not supported" in listed.json()[1]["error"]


def test_a_failed_document_is_never_opened_or_cited(api: httpx.Client, collection_id: int) -> None:
    documents = f"/collections/{collection_id}/documents"
    api.post(f"{documents}/upload", files={"file": ("sky.pdf", b"%PDF sky is blue")})
    failed = api.get(documents).json()[0]

    opened = api.get(f"{documents}/{failed['id']}")
    answer = api.post(
        f"/collections/{collection_id}/answer", json={"question": "What colour is the sky?"}
    )

    assert failed["status"] == "failed"
    assert opened.status_code == 404
    assert answer.json()["answered"] is False


def test_readers_see_the_document_list_and_others_do_not(
    api: httpx.Client, user: httpx.Client, user_id: int, collection_id: int
) -> None:
    documents = f"/collections/{collection_id}/documents"
    api.post(documents, json={"title": "Notes", "content": "The sky is blue."})

    before = user.get(documents)
    api.put(f"/collections/{collection_id}/grants/{user_id}", json={"role": "reader"})
    after = user.get(documents)

    assert before.status_code == 404
    assert [d["title"] for d in after.json()] == ["Notes"]
