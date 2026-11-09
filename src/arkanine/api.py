import os
from typing import Any, Optional

import httpx
import psycopg
from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel

from arkanine.db import create_schema
from arkanine.repository import CollectionRepository, DocumentRepository

CHECK_TIMEOUT_SECONDS = 2


class CreateCollectionRequest(BaseModel):
    """Request to create a collection."""

    name: str


class CollectionResponse(BaseModel):
    """Response with collection details."""

    id: int
    name: str


class IngestDocumentRequest(BaseModel):
    """Request to ingest a document."""

    title: str
    content: str


class DocumentResponse(BaseModel):
    """Response with document details."""

    id: int
    collection_id: int
    title: str


class AnswerRequest(BaseModel):
    """Request to answer a question."""

    question: str


class CitationResponse(BaseModel):
    """A citation in an answer."""

    document_id: int
    text: str
    start_offset: int
    end_offset: int


class AnswerResponse(BaseModel):
    """Response with answer and citations."""

    answer: str
    citations: list[CitationResponse]


def _check_database() -> str:
    try:
        with psycopg.connect(
            os.environ["DATABASE_URL"], connect_timeout=CHECK_TIMEOUT_SECONDS
        ) as conn:
            conn.execute("SELECT 1")
    except (KeyError, psycopg.Error):
        return "unavailable"
    return "ok"


def _check_inference() -> str:
    try:
        base_url = os.environ["INFERENCE_BASE_URL"].rstrip("/")
        httpx.get(f"{base_url}/models", timeout=CHECK_TIMEOUT_SECONDS).raise_for_status()
    except (KeyError, httpx.HTTPError):
        return "unavailable"
    return "ok"


def create_app() -> FastAPI:
    app = FastAPI(title="Arkanine")

    @app.on_event("startup")
    def startup() -> None:
        """Initialize database schema on startup."""
        create_schema()

    @app.get("/health")
    def health(response: Response) -> dict[str, object]:
        checks = {"database": _check_database(), "inference": _check_inference()}
        healthy = all(state == "ok" for state in checks.values())
        if not healthy:
            response.status_code = 503
        return {"status": "ok" if healthy else "degraded", "checks": checks}

    @app.post("/collections", status_code=201)
    def create_collection(req: CreateCollectionRequest) -> CollectionResponse:
        """Create a new collection."""
        collection = CollectionRepository.create(req.name)
        return CollectionResponse(id=collection.id, name=collection.name)

    @app.post("/collections/{collection_id}/documents", status_code=201)
    def ingest_document(collection_id: int, req: IngestDocumentRequest) -> DocumentResponse:
        """Ingest a document into a collection."""
        collection = CollectionRepository.get_by_id(collection_id)
        if not collection:
            raise HTTPException(status_code=404, detail="Collection not found")

        doc = DocumentRepository.create(collection_id, req.title, req.content)
        return DocumentResponse(id=doc.id, collection_id=doc.collection_id, title=doc.title)

    @app.post("/collections/{collection_id}/answer")
    def answer_question(collection_id: int, req: AnswerRequest) -> AnswerResponse:
        """Answer a question using documents in a collection."""
        collection = CollectionRepository.get_by_id(collection_id)
        if not collection:
            raise HTTPException(status_code=404, detail="Collection not found")

        docs = DocumentRepository.get_by_collection(collection_id)
        if not docs:
            return AnswerResponse(
                answer="I don't have any documents to answer from.",
                citations=[],
            )

        # Build context from all documents
        context = "\n\n".join(f"[Document {doc.id}] {doc.title}:\n{doc.content}" for doc in docs)

        # Call inference API with RAG prompt
        base_url = os.environ["INFERENCE_BASE_URL"].rstrip("/")
        inference_response = httpx.post(
            f"{base_url}/chat/completions",
            json={
                "model": "fake-chat",
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You are a helpful assistant. Answer questions based only on "
                            "the provided documents. When citing information, include "
                            "[Document ID] references. If the documents don't contain the "
                            "answer, say so clearly."
                        ),
                    },
                    {
                        "role": "user",
                        "content": f"Documents:\n{context}\n\nQuestion: {req.question}",
                    },
                ],
            },
        )
        inference_response.raise_for_status()
        inference_data = inference_response.json()

        answer_text = inference_data["choices"][0]["message"]["content"]

        # Extract citations by finding referenced documents in the answer
        # and locating relevant passages in their content
        citations = []
        for doc in docs:
            if f"[Document {doc.id}]" in answer_text:
                # Find the most relevant passage: extract a sentence or phrase
                # containing keywords from the answer that also appear in the doc
                passage = _extract_best_passage(doc.content, answer_text)
                if passage and passage["text"]:
                    citations.append(
                        CitationResponse(
                            document_id=doc.id,
                            text=passage["text"],
                            start_offset=passage["start"],
                            end_offset=passage["end"],
                        )
                    )

        return AnswerResponse(answer=answer_text, citations=citations)

    return app


def _extract_best_passage(content: str, answer: str) -> Optional[dict[str, Any]]:
    """Extract a passage from content that relates to the answer.

    Returns a dict with 'text', 'start', and 'end' keys, or None if no passage found.
    """
    # Split content into sentences
    sentences = [s.strip() for s in content.split(". ") if s.strip()]
    if not sentences:
        return None

    # Find the sentence that best overlaps with the answer
    best_sentence = None
    best_overlap = 0

    for sentence in sentences:
        # Count word overlap between sentence and answer
        sentence_words = set(sentence.lower().split())
        answer_words = set(answer.lower().split())
        overlap = len(sentence_words & answer_words)

        if overlap > best_overlap:
            best_overlap = overlap
            best_sentence = sentence

    if best_sentence is None:
        # Fallback: return first sentence
        best_sentence = sentences[0]

    # Find position in original content
    start_offset = content.find(best_sentence)
    if start_offset == -1:
        start_offset = 0

    end_offset = start_offset + len(best_sentence)

    return {"text": best_sentence, "start": start_offset, "end": end_offset}


app = create_app()
