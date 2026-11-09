import os

import httpx
import psycopg
from fastapi import FastAPI, HTTPException, Response, UploadFile
from pydantic import BaseModel, field_validator

from arkanine.answering import build_messages, not_found, parse_reply
from arkanine.db import create_schema
from arkanine.extraction import (
    SUPPORTED_EXTENSIONS,
    UnreadableFile,
    UnsupportedFileType,
    check_document_text,
    extract_text,
)
from arkanine.passages import find_relevant_passages
from arkanine.repository import (
    CollectionRepository,
    DocumentRepository,
    DuplicateCollectionName,
)

CHECK_TIMEOUT_SECONDS = 2
INFERENCE_TIMEOUT_SECONDS = 120


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

    @field_validator("title", "content")
    @classmethod
    def _storable(cls, value: str) -> str:
        try:
            return check_document_text(value)
        except UnreadableFile as error:
            raise ValueError(str(error)) from None


class DocumentResponse(BaseModel):
    """Response with document details."""

    id: int
    collection_id: int
    title: str


class DocumentContentResponse(BaseModel):
    """A document with its full content, for opening a citation in context."""

    id: int
    collection_id: int
    title: str
    content: str


class AnswerRequest(BaseModel):
    """Request to answer a question."""

    question: str


class CitationResponse(BaseModel):
    """A citation in an answer."""

    document_id: int
    document_title: str
    text: str
    start_offset: int
    end_offset: int


class AnswerResponse(BaseModel):
    """Response with answer and citations.

    `answered` is false when the documents don't contain an answer.
    """

    answer: str
    answered: bool
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
        try:
            collection = CollectionRepository.create(req.name)
        except DuplicateCollectionName:
            raise HTTPException(status_code=409, detail="Collection name already exists") from None
        return CollectionResponse(id=collection.id, name=collection.name)

    @app.post("/collections/{collection_id}/documents", status_code=201)
    def ingest_document(collection_id: int, req: IngestDocumentRequest) -> DocumentResponse:
        """Ingest a document into a collection."""
        _require_collection(collection_id)
        return _ingest(collection_id, req.title, req.content)

    @app.post("/collections/{collection_id}/documents/upload", status_code=201)
    def upload_document(collection_id: int, file: UploadFile) -> DocumentResponse:
        """Ingest an uploaded file into a collection, titled by its filename."""
        _require_collection(collection_id)
        filename = file.filename or "untitled"
        try:
            content = extract_text(filename, file.file.read())
        except UnsupportedFileType:
            raise HTTPException(
                status_code=415,
                detail=f"{filename}: unsupported file type; supported: "
                + ", ".join(SUPPORTED_EXTENSIONS),
            ) from None
        except UnreadableFile as error:
            raise HTTPException(status_code=422, detail=f"{filename}: {error}") from None

        return _ingest(collection_id, filename, content)

    @app.get("/collections/{collection_id}/documents/{document_id}")
    def get_document(collection_id: int, document_id: int) -> DocumentContentResponse:
        """Open a document in full, so a citation's offsets can be shown in context."""
        doc = DocumentRepository.get(collection_id, document_id)
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")
        return DocumentContentResponse(
            id=doc.id, collection_id=doc.collection_id, title=doc.title, content=doc.content
        )

    @app.post("/collections/{collection_id}/answer")
    def answer_question(collection_id: int, req: AnswerRequest) -> AnswerResponse:
        """Answer a question using documents in a collection."""
        _require_collection(collection_id)
        docs = DocumentRepository.get_by_collection(collection_id)
        passages = find_relevant_passages(docs, req.question)
        if not passages:
            result = not_found()
        else:
            reply = _complete(build_messages(passages, req.question))
            result = parse_reply(reply, passages)

        return AnswerResponse(
            answer=result.answer,
            answered=result.answered,
            citations=[
                CitationResponse(
                    document_id=passage.document.id,
                    document_title=passage.document.title,
                    text=passage.text,
                    start_offset=passage.start_offset,
                    end_offset=passage.end_offset,
                )
                for passage in result.citations
            ],
        )

    return app


def _require_collection(collection_id: int) -> None:
    if not CollectionRepository.get_by_id(collection_id):
        raise HTTPException(status_code=404, detail="Collection not found")


def _ingest(collection_id: int, title: str, content: str) -> DocumentResponse:
    doc = DocumentRepository.create(collection_id, title, content)
    return DocumentResponse(id=doc.id, collection_id=doc.collection_id, title=doc.title)


def _complete(messages: list[dict[str, str]]) -> str:
    """Ask the inference server for a chat completion. The model is offered no tools."""
    model = os.environ.get("INFERENCE_MODEL")
    if not model:
        raise HTTPException(status_code=503, detail="No inference model is configured")
    base_url = os.environ["INFERENCE_BASE_URL"].rstrip("/")
    try:
        response = httpx.post(
            f"{base_url}/chat/completions",
            json={"model": model, "messages": messages},
            timeout=INFERENCE_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return str(response.json()["choices"][0]["message"]["content"])
    except (httpx.HTTPError, KeyError, IndexError, ValueError) as error:
        raise HTTPException(status_code=502, detail="Inference server failed") from error


app = create_app()
