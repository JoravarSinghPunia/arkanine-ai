import uuid
from collections.abc import Callable

import httpx


def test_the_configured_administrator_can_sign_in(
    anon: httpx.Client, admin_credentials: dict[str, str]
) -> None:
    response = anon.post("/sessions", json=admin_credentials)

    assert response.status_code == 201
    assert response.json()["token"]


def test_signing_in_with_a_wrong_password_is_refused(
    anon: httpx.Client, admin_credentials: dict[str, str]
) -> None:
    response = anon.post("/sessions", json={**admin_credentials, "password": "wrong"})

    assert response.status_code == 401


def test_collections_require_signing_in(anon: httpx.Client) -> None:
    assert anon.get("/collections").status_code == 401
    assert anon.post("/collections", json={"name": "anything"}).status_code == 401


def test_users_see_only_the_collections_they_are_granted(
    api: httpx.Client, user: httpx.Client, user_id: int, collection_id: int
) -> None:
    other = api.post("/collections", json={"name": f"collection-{uuid.uuid4()}"}).json()

    before = user.get("/collections")
    granted = api.put(f"/collections/{collection_id}/grants/{user_id}", json={"role": "reader"})
    after = user.get("/collections")

    assert before.status_code == 200 and before.json() == []
    assert granted.status_code == 200
    assert [c["id"] for c in after.json()] == [collection_id]
    assert other["id"] not in [c["id"] for c in after.json()]


def test_a_user_without_a_grant_cannot_reach_a_collection(
    user: httpx.Client, user_id: int, collection_id: int, ingest: Callable[[str, str], int]
) -> None:
    document_id = ingest("Sky facts", "The sky is blue.")
    base = f"/collections/{collection_id}"

    responses = [
        user.get(f"{base}/documents/{document_id}"),
        user.post(f"{base}/answer", json={"question": "What colour is the sky?"}),
        user.post(f"{base}/documents", json={"title": "x", "content": "y"}),
        user.post(f"{base}/documents/upload", files={"file": ("x.txt", b"y", "text/plain")}),
    ]

    assert [r.status_code for r in responses] == [404, 404, 404, 404]


def test_a_reader_can_ask_and_open_documents_but_not_ingest(
    api: httpx.Client,
    user: httpx.Client,
    user_id: int,
    collection_id: int,
    ingest: Callable[[str, str], int],
) -> None:
    document_id = ingest("Sky facts", "The sky is blue.")
    api.put(f"/collections/{collection_id}/grants/{user_id}", json={"role": "reader"})
    base = f"/collections/{collection_id}"

    answer = user.post(f"{base}/answer", json={"question": "What colour is the sky?"})
    opened = user.get(f"{base}/documents/{document_id}")
    ingested = user.post(f"{base}/documents", json={"title": "x", "content": "y"})

    assert [c["text"] for c in answer.json()["citations"]] == ["The sky is blue."]
    assert opened.json()["content"] == "The sky is blue."
    assert ingested.status_code == 403


def test_an_editor_can_ingest_documents(
    api: httpx.Client, user: httpx.Client, user_id: int, collection_id: int
) -> None:
    api.put(f"/collections/{collection_id}/grants/{user_id}", json={"role": "editor"})

    response = user.post(
        f"/collections/{collection_id}/documents", json={"title": "Notes", "content": "Hi."}
    )

    assert response.status_code == 201


def test_only_administrators_manage_accounts_collections_and_grants(
    user: httpx.Client, user_id: int, collection_id: int
) -> None:
    responses = [
        user.post("/users", json={"username": f"u-{uuid.uuid4()}", "password": "pw"}),
        user.post("/collections", json={"name": f"collection-{uuid.uuid4()}"}),
        user.put(f"/collections/{collection_id}/grants/{user_id}", json={"role": "editor"}),
    ]

    assert [r.status_code for r in responses] == [403, 403, 403]


def test_revoking_access_takes_effect_immediately(
    api: httpx.Client,
    user: httpx.Client,
    user_id: int,
    collection_id: int,
    ingest: Callable[[str, str], int],
) -> None:
    document_id = ingest("Sky facts", "The sky is blue.")
    grant = f"/collections/{collection_id}/grants/{user_id}"
    api.put(grant, json={"role": "reader"})
    assert user.get(f"/collections/{collection_id}/documents/{document_id}").is_success

    revoked = api.delete(grant)

    assert revoked.status_code == 204
    assert user.get("/collections").json() == []
    assert user.get(f"/collections/{collection_id}/documents/{document_id}").status_code == 404
    assert (
        user.post(
            f"/collections/{collection_id}/answer", json={"question": "What colour is the sky?"}
        ).status_code
        == 404
    )


def test_changing_a_role_takes_effect_immediately(
    api: httpx.Client, user: httpx.Client, user_id: int, collection_id: int
) -> None:
    grant = f"/collections/{collection_id}/grants/{user_id}"
    documents = f"/collections/{collection_id}/documents"
    api.put(grant, json={"role": "editor"})
    assert user.post(documents, json={"title": "a", "content": "b"}).status_code == 201

    api.put(grant, json={"role": "reader"})

    assert user.post(documents, json={"title": "a", "content": "b"}).status_code == 403


def _collection_with(api: httpx.Client, title: str, content: str) -> tuple[int, int]:
    collection = api.post("/collections", json={"name": f"collection-{uuid.uuid4()}"}).json()
    document = api.post(
        f"/collections/{collection['id']}/documents", json={"title": title, "content": content}
    ).json()
    return int(collection["id"]), int(document["id"])


def test_answers_never_draw_on_collections_the_user_cannot_access(
    api: httpx.Client, fake_inference: httpx.Client, user: httpx.Client, user_id: int
) -> None:
    allowed, allowed_doc = _collection_with(api, "Public", "The sky is blue.")
    # Matches the question better, so it would win ranking if it were ever considered.
    _collection_with(api, "Secret", "The secret sky colour today is green.")
    api.put(f"/collections/{allowed}/grants/{user_id}", json={"role": "reader"})

    answer = user.post("/answer", json={"question": "What secret colour is the sky today?"})
    sent = fake_inference.get("/_test/last_request").json()

    assert answer.status_code == 200
    assert [(c["collection_id"], c["document_id"]) for c in answer.json()["citations"]] == [
        (allowed, allowed_doc)
    ]
    assert "green" not in answer.json()["answer"]
    assert "green" not in str(sent["messages"])


def test_answers_can_be_narrowed_to_chosen_collections(
    api: httpx.Client, user: httpx.Client, user_id: int
) -> None:
    first, _ = _collection_with(api, "First", "The sky is blue.")
    second, second_doc = _collection_with(api, "Second", "The sky is grey in winter.")
    for collection in (first, second):
        api.put(f"/collections/{collection}/grants/{user_id}", json={"role": "reader"})

    answer = user.post(
        "/answer", json={"question": "What colour is the sky?", "collection_ids": [second]}
    )

    assert [c["document_id"] for c in answer.json()["citations"]] == [second_doc]


def test_asking_an_inaccessible_collection_by_id_is_not_found(
    api: httpx.Client, user: httpx.Client, user_id: int
) -> None:
    allowed, _ = _collection_with(api, "Public", "The sky is blue.")
    secret, _ = _collection_with(api, "Secret", "The sky is green.")
    api.put(f"/collections/{allowed}/grants/{user_id}", json={"role": "reader"})

    response = user.post(
        "/answer", json={"question": "What colour is the sky?", "collection_ids": [allowed, secret]}
    )

    assert response.status_code == 404


def test_a_user_with_no_collections_is_told_there_is_no_answer(
    user: httpx.Client, user_id: int
) -> None:
    response = user.post("/answer", json={"question": "What colour is the sky?"})

    assert response.status_code == 200
    assert response.json()["answered"] is False
    assert response.json()["citations"] == []


def test_accounts_created_through_the_api_are_never_administrators(
    anon: httpx.Client, api: httpx.Client
) -> None:
    credentials = {"username": f"user-{uuid.uuid4()}", "password": "pw", "is_admin": True}

    created = api.post("/users", json=credentials)
    token = anon.post("/sessions", json=credentials).json()["token"]
    as_new_user = anon.post(
        "/collections",
        json={"name": f"collection-{uuid.uuid4()}"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert created.status_code == 201
    assert as_new_user.status_code == 403
