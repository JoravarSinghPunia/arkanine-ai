"""Tests for Collection creation and document ingestion."""
import time

import httpx


def test_create_collection(api: httpx.Client) -> None:
    """Can create a named Collection."""
    # Use timestamps to ensure unique names
    unique_name = f"my-docs-{int(time.time()*1000)}"
    response = api.post("/collections", json={"name": unique_name})

    assert response.status_code == 201
    data = response.json()
    assert data["id"]
    assert data["name"] == unique_name


def test_ingest_document(api: httpx.Client) -> None:
    """Can ingest text into a Collection."""
    # Use timestamps to ensure unique names
    unique_name = f"docs-ingest-{int(time.time()*1000)}"
    # Create a collection
    collection = api.post("/collections", json={"name": unique_name}).json()
    collection_id = collection["id"]

    # Ingest a document
    response = api.post(
        f"/collections/{collection_id}/documents",
        json={"content": "The sky is blue.", "title": "Sky Facts"},
    )

    assert response.status_code == 201
    data = response.json()
    assert data["id"]
    assert data["title"] == "Sky Facts"
    assert data["collection_id"] == collection_id


def test_answer_question_with_citations(api: httpx.Client) -> None:
    """Can answer a question with citations from ingested documents."""
    # Use timestamps to ensure unique names
    unique_name = f"docs-answer-{int(time.time()*1000)}"
    # Create a collection
    collection = api.post("/collections", json={"name": unique_name}).json()
    collection_id = collection["id"]

    # Ingest a document with facts
    api.post(
        f"/collections/{collection_id}/documents",
        json={"content": "The sky is blue. Grass is green.", "title": "Facts"},
    )

    # Ask a question
    response = api.post(
        f"/collections/{collection_id}/answer",
        json={"question": "What color is the sky?"},
    )

    assert response.status_code == 200
    data = response.json()
    assert "answer" in data
    assert "citations" in data
    assert len(data["citations"]) > 0
    assert isinstance(data["citations"][0], dict)
    assert "document_id" in data["citations"][0]
    assert "text" in data["citations"][0]
