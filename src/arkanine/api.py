import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Annotated, Optional

import psycopg
from fastapi import Depends, FastAPI, HTTPException, Response, UploadFile
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, field_validator

from arkanine import inference
from arkanine.answering import (
    NOT_FOUND_ANSWER,
    NOT_FOUND_ANYWHERE_ANSWER,
    build_messages,
    not_found,
    parse_reply,
)
from arkanine.db import create_schema
from arkanine.extraction import (
    MAX_UPLOAD_BYTES,
    SUPPORTED_EXTENSIONS,
    UnreadableFile,
    UnsupportedFileType,
    check_document_text,
    extract_text,
)
from arkanine.models import DocumentStatus, Role, User
from arkanine.passages import passage_spans
from arkanine.repository import (
    AccessRepository,
    CollectionRepository,
    DocumentRepository,
    DuplicateCollectionName,
    DuplicateUsername,
    PassageRepository,
    UserRepository,
)

CHECK_TIMEOUT_SECONDS = 2
PASSAGES_PER_ANSWER = 8


class SignInRequest(BaseModel):
    username: str
    password: str


class SessionResponse(BaseModel):
    token: str


class CreateUserRequest(BaseModel):
    """Request to create a local account. Only the configured administrator is an admin."""

    username: str
    password: str


class UserResponse(BaseModel):
    id: int
    username: str


class GrantRequest(BaseModel):
    role: Role


class GrantResponse(BaseModel):
    user_id: int
    collection_id: int
    role: Role


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


class DocumentStatusResponse(BaseModel):
    """A document in a collection's list. `error` says why a failed upload was rejected."""

    id: int
    title: str
    status: DocumentStatus
    error: Optional[str]


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


class AnswerAcrossCollectionsRequest(BaseModel):
    """Request to answer a question from the user's Collections.

    `collection_ids` narrows the search; by default every accessible Collection is used.
    """

    question: str
    collection_ids: Optional[list[int]] = None


class CitationResponse(BaseModel):
    """A citation in an answer."""

    collection_id: int
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


_bearer = HTTPBearer(auto_error=False)


def current_user(
    credentials: Annotated[Optional[HTTPAuthorizationCredentials], Depends(_bearer)],
) -> User:
    """The signed-in user, looked up on every request so revocation is immediate."""
    user = UserRepository.by_token(credentials.credentials) if credentials else None
    if not user:
        raise HTTPException(
            status_code=401,
            detail="Sign in required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


CurrentUser = Annotated[User, Depends(current_user)]


def admin_user(user: CurrentUser) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Administrator access required")
    return user


AdminUser = Annotated[User, Depends(admin_user)]


def _bootstrap_admin() -> None:
    username = os.environ.get("ARKANINE_ADMIN_USERNAME")
    password = os.environ.get("ARKANINE_ADMIN_PASSWORD")
    if username and password:
        UserRepository.ensure_admin(username, password)


def create_app() -> FastAPI:
    app = FastAPI(title="Arkanine")

    @app.on_event("startup")
    def startup() -> None:
        """Initialize database schema on startup."""
        create_schema()
        _bootstrap_admin()

    @app.get("/health")
    def health(response: Response) -> dict[str, object]:
        checks = {
            "database": _check_database(),
            "inference": inference.chat_endpoint().check(),
            "embeddings": inference.embedding_endpoint().check(),
        }
        healthy = all(state == "ok" for state in checks.values())
        if not healthy:
            response.status_code = 503
        return {"status": "ok" if healthy else "degraded", "checks": checks}

    @app.post("/sessions", status_code=201)
    def sign_in(req: SignInRequest) -> SessionResponse:
        """Sign in with a local account and receive a bearer token."""
        token = UserRepository.sign_in(req.username, req.password)
        if not token:
            raise HTTPException(status_code=401, detail="Wrong username or password")
        return SessionResponse(token=token)

    @app.get("/collections")
    def list_collections(user: CurrentUser) -> list[CollectionResponse]:
        """List the Collections the user can access."""
        return [
            CollectionResponse(id=c.id, name=c.name)
            for c in AccessRepository.accessible_collections(user)
        ]

    @app.post("/users", status_code=201)
    def create_user(req: CreateUserRequest, _: AdminUser) -> UserResponse:
        """Create a local account."""
        try:
            created = UserRepository.create(req.username, req.password)
        except DuplicateUsername:
            raise HTTPException(status_code=409, detail="Username already exists") from None
        return UserResponse(id=created.id, username=created.username)

    @app.put("/collections/{collection_id}/grants/{user_id}")
    def grant_access(
        collection_id: int, user_id: int, req: GrantRequest, _: AdminUser
    ) -> GrantResponse:
        """Give a user a role on a Collection, replacing any role they had."""
        _require_collection(collection_id)
        if not UserRepository.get_by_id(user_id):
            raise HTTPException(status_code=404, detail="User not found")
        AccessRepository.grant(user_id, collection_id, req.role)
        return GrantResponse(user_id=user_id, collection_id=collection_id, role=req.role)

    @app.delete("/collections/{collection_id}/grants/{user_id}", status_code=204)
    def revoke_access(collection_id: int, user_id: int, _: AdminUser) -> Response:
        """Remove a user's access to a Collection. Revoking absent access is a no-op."""
        AccessRepository.revoke(user_id, collection_id)
        return Response(status_code=204)

    @app.post("/collections", status_code=201)
    def create_collection(req: CreateCollectionRequest, _: AdminUser) -> CollectionResponse:
        """Create a new collection."""
        try:
            collection = CollectionRepository.create(req.name)
        except DuplicateCollectionName:
            raise HTTPException(status_code=409, detail="Collection name already exists") from None
        return CollectionResponse(id=collection.id, name=collection.name)

    @app.post("/collections/{collection_id}/documents", status_code=201)
    def ingest_document(
        collection_id: int, req: IngestDocumentRequest, user: CurrentUser
    ) -> DocumentResponse:
        """Ingest a document into a collection."""
        _require_role(user, collection_id, "editor")
        return _ingest(collection_id, req.title, req.content)

    @app.post("/collections/{collection_id}/documents/upload", status_code=201)
    def upload_document(
        collection_id: int, file: UploadFile, user: CurrentUser
    ) -> DocumentResponse:
        """Ingest an uploaded file into a collection, titled by its filename."""
        _require_role(user, collection_id, "editor")
        filename = file.filename or "untitled"
        data = file.file.read(MAX_UPLOAD_BYTES + 1)
        if len(data) > MAX_UPLOAD_BYTES:
            reason = f"larger than the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB upload limit"
            DocumentRepository.record_failure(collection_id, filename, reason)
            raise HTTPException(status_code=413, detail=f"{filename}: {reason}")
        try:
            content = extract_text(filename, data)
        except UnsupportedFileType as error:
            reason = f"{error}; supported: " + ", ".join(SUPPORTED_EXTENSIONS)
            DocumentRepository.record_failure(collection_id, filename, reason)
            raise HTTPException(status_code=415, detail=f"{filename}: {reason}") from None
        except UnreadableFile as error:
            DocumentRepository.record_failure(collection_id, filename, str(error))
            raise HTTPException(status_code=422, detail=f"{filename}: {error}") from None

        return _ingest(collection_id, filename, content)

    @app.get("/collections/{collection_id}/documents")
    def list_documents(collection_id: int, user: CurrentUser) -> list[DocumentStatusResponse]:
        """List a collection's documents with their ingestion status, oldest first."""
        _require_role(user, collection_id, "reader")
        return [
            DocumentStatusResponse(id=d.id, title=d.title, status=d.status, error=d.error)
            for d in DocumentRepository.list_by_collection(collection_id)
        ]

    @app.get("/collections/{collection_id}/documents/{document_id}")
    def get_document(
        collection_id: int, document_id: int, user: CurrentUser
    ) -> DocumentContentResponse:
        """Open a document in full, so a citation's offsets can be shown in context."""
        _require_role(user, collection_id, "reader")
        doc = DocumentRepository.get(collection_id, document_id)
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")
        return DocumentContentResponse(
            id=doc.id, collection_id=doc.collection_id, title=doc.title, content=doc.content
        )

    @app.post("/collections/{collection_id}/answer")
    def answer_question(
        collection_id: int, req: AnswerRequest, user: CurrentUser
    ) -> AnswerResponse:
        """Answer a question using documents in a collection."""
        _require_role(user, collection_id, "reader")
        return _answer([collection_id], req.question, NOT_FOUND_ANSWER)

    @app.post("/answer")
    def answer_across_collections(
        req: AnswerAcrossCollectionsRequest, user: CurrentUser
    ) -> AnswerResponse:
        """Answer a question from the Collections the user can access.

        Passages are filtered to those Collections before ranking, so nothing the user
        cannot access ever reaches the model or the citations.
        """
        accessible = {c.id for c in AccessRepository.accessible_collections(user)}
        if req.collection_ids is None:
            collection_ids = sorted(accessible)
        elif set(req.collection_ids) <= accessible:
            collection_ids = req.collection_ids
        else:
            raise HTTPException(status_code=404, detail="Collection not found")
        return _answer(collection_ids, req.question, NOT_FOUND_ANYWHERE_ANSWER)

    return app


def _require_role(user: User, collection_id: int, needed: Role) -> None:
    """Refuse unless the user holds `needed` (editor implies reader) on the Collection.

    Without any access the Collection is reported as not found, so its existence isn't
    revealed.
    """
    role = AccessRepository.role(user, collection_id)
    if role is None:
        raise HTTPException(status_code=404, detail="Collection not found")
    if needed == "editor" and role != "editor":
        raise HTTPException(status_code=403, detail="Editor access required")


def _require_collection(collection_id: int) -> None:
    if not CollectionRepository.get_by_id(collection_id):
        raise HTTPException(status_code=404, detail="Collection not found")


@contextmanager
def _inference_errors(kind: str) -> Iterator[None]:
    try:
        yield
    except inference.NotConfigured:
        raise HTTPException(status_code=503, detail=f"No {kind} model is configured") from None
    except inference.InferenceFailed as error:
        raise HTTPException(status_code=502, detail=f"{kind.capitalize()} server failed") from error


def _embedded_spans(content: str) -> list[tuple[int, int, list[float]]]:
    spans = passage_spans(content)
    with _inference_errors("embedding"):
        vectors = inference.embed([content[start:end] for start, end in spans], "document")
    return [(start, end, vector) for (start, end), vector in zip(spans, vectors)]


def _ingest(collection_id: int, title: str, content: str) -> DocumentResponse:
    with _inference_errors("embedding"):
        model = inference.embedding_model()
    doc = DocumentRepository.create(collection_id, title, content, model, _embedded_spans(content))
    return DocumentResponse(id=doc.id, collection_id=doc.collection_id, title=doc.title)


def _answer(collection_ids: list[int], question: str, not_found_answer: str) -> AnswerResponse:
    passages = []
    if collection_ids:
        with _inference_errors("embedding"):
            model = inference.embedding_model()
        # Documents ingested before this embedding model was configured.
        for doc in PassageRepository.unembedded_documents(collection_ids, model):
            PassageRepository.add(doc.id, model, _embedded_spans(doc.content))
        with _inference_errors("embedding"):
            [query] = inference.embed([question], "query")
        passages = PassageRepository.nearest(collection_ids, model, query, PASSAGES_PER_ANSWER)
    if not passages:
        result = not_found(not_found_answer)
    else:
        with _inference_errors("inference"):
            reply = inference.complete(build_messages(passages, question))
        result = parse_reply(reply, passages, not_found_answer)

    return AnswerResponse(
        answer=result.answer,
        answered=result.answered,
        citations=[
            CitationResponse(
                collection_id=passage.document.collection_id,
                document_id=passage.document.id,
                document_title=passage.document.title,
                text=passage.text,
                start_offset=passage.start_offset,
                end_offset=passage.end_offset,
            )
            for passage in result.citations
        ],
    )


app = create_app()
