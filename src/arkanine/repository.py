"""Repository layer for database operations."""

import os
from typing import Any, Optional, cast

import psycopg

from arkanine.accounts import (
    UNKNOWN_USER_HASH,
    hash_password,
    hash_token,
    new_token,
    verify_password,
)
from arkanine.models import Collection, Document, DocumentSummary, Role, User


class DuplicateCollectionName(Exception):
    """A Collection with this name already exists."""


def _execute_query(sql: str, params: tuple[object, ...], fetch_one: bool = False) -> Any:
    """Execute a query and commit, returning one or all rows."""
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            result = cur.fetchone() if fetch_one else cur.fetchall()
            conn.commit()
    return result


def _collection(row: tuple[Any, ...]) -> Collection:
    return Collection(id=row[0], name=row[1])


def _document(row: tuple[Any, ...]) -> Document:
    return Document(id=row[0], collection_id=row[1], title=row[2], content=row[3])


class CollectionRepository:
    """Repository for Collection operations."""

    @staticmethod
    def create(name: str) -> Collection:
        """Create a new collection."""
        try:
            row = _execute_query(
                "INSERT INTO collections (name) VALUES (%s) RETURNING id, name",
                (name,),
                fetch_one=True,
            )
        except psycopg.errors.UniqueViolation as error:
            raise DuplicateCollectionName(name) from error
        if not row:
            raise RuntimeError("Failed to create collection")
        return _collection(row)

    @staticmethod
    def get_by_id(collection_id: int) -> Optional[Collection]:
        """Get a collection by ID."""
        row = _execute_query(
            "SELECT id, name FROM collections WHERE id = %s",
            (collection_id,),
            fetch_one=True,
        )
        if not row:
            return None
        return _collection(row)

    @staticmethod
    def list_all() -> list[Collection]:
        rows = _execute_query("SELECT id, name FROM collections ORDER BY id", ())
        return [_collection(row) for row in rows]


class DocumentRepository:
    """Repository for Document operations."""

    @staticmethod
    def create(collection_id: int, title: str, content: str) -> Document:
        """Create a new document in a collection."""
        row = _execute_query(
            (
                "INSERT INTO documents (collection_id, title, content) "
                "VALUES (%s, %s, %s) "
                "RETURNING id, collection_id, title, content"
            ),
            (collection_id, title, content),
            fetch_one=True,
        )
        if not row:
            raise RuntimeError("Failed to create document")
        return _document(row)

    @staticmethod
    def record_failure(collection_id: int, title: str, error: str) -> None:
        """Keep a rejected upload in the document list, with the reason it was rejected."""
        _execute_query(
            (
                "INSERT INTO documents (collection_id, title, content, status, error) "
                "VALUES (%s, %s, '', 'failed', %s) RETURNING id"
            ),
            (collection_id, title, error),
            fetch_one=True,
        )

    @staticmethod
    def list_by_collection(collection_id: int) -> list[DocumentSummary]:
        """Every document in a collection, including failed uploads, oldest first."""
        rows = _execute_query(
            "SELECT id, title, status, error FROM documents WHERE collection_id = %s ORDER BY id",
            (collection_id,),
        )
        return [
            DocumentSummary(id=row[0], title=row[1], status=row[2], error=row[3]) for row in rows
        ]

    @staticmethod
    def get(collection_id: int, document_id: int) -> Optional[Document]:
        """Get a document by ID, only if it belongs to the given collection."""
        row = _execute_query(
            (
                "SELECT id, collection_id, title, content FROM documents "
                "WHERE collection_id = %s AND id = %s AND status = 'ready'"
            ),
            (collection_id, document_id),
            fetch_one=True,
        )
        if not row:
            return None
        return _document(row)

    @staticmethod
    def get_by_collection(collection_id: int) -> list[Document]:
        """Get all documents in a collection."""
        rows = _execute_query(
            (
                "SELECT id, collection_id, title, content FROM documents "
                "WHERE collection_id = %s AND status = 'ready' ORDER BY id"
            ),
            (collection_id,),
        )
        return [_document(row) for row in rows]

    @staticmethod
    def get_by_collections(collection_ids: list[int]) -> list[Document]:
        """Get all documents in any of the given collections."""
        rows = _execute_query(
            (
                "SELECT id, collection_id, title, content FROM documents "
                "WHERE collection_id = ANY(%s) AND status = 'ready' ORDER BY id"
            ),
            (collection_ids,),
        )
        return [_document(row) for row in rows]


class DuplicateUsername(Exception):
    """A user with this username already exists."""


def _user(row: tuple[Any, ...]) -> User:
    return User(id=row[0], username=row[1], is_admin=row[2])


class UserRepository:
    """Repository for local accounts and their sessions."""

    @staticmethod
    def create(username: str, password: str) -> User:
        """Create an account that is not an administrator."""
        try:
            row = _execute_query(
                (
                    "INSERT INTO users (username, password_hash) VALUES (%s, %s) "
                    "RETURNING id, username, is_admin"
                ),
                (username, hash_password(password)),
                fetch_one=True,
            )
        except psycopg.errors.UniqueViolation as error:
            raise DuplicateUsername(username) from error
        return _user(row)

    @staticmethod
    def ensure_admin(username: str, password: str) -> None:
        """Create the administrator if no account has this username yet."""
        _execute_query(
            (
                "INSERT INTO users (username, password_hash, is_admin) VALUES (%s, %s, TRUE) "
                "ON CONFLICT (username) DO NOTHING RETURNING id"
            ),
            (username, hash_password(password)),
            fetch_one=True,
        )

    @staticmethod
    def sign_in(username: str, password: str) -> Optional[str]:
        """Return a new session token, or None if the credentials are wrong."""
        row = _execute_query(
            "SELECT id, password_hash FROM users WHERE username = %s", (username,), fetch_one=True
        )
        if not verify_password(password, row[1] if row else UNKNOWN_USER_HASH) or not row:
            return None
        token = new_token()
        _execute_query(
            "INSERT INTO sessions (token_hash, user_id) VALUES (%s, %s) RETURNING user_id",
            (hash_token(token), row[0]),
            fetch_one=True,
        )
        return token

    @staticmethod
    def get_by_id(user_id: int) -> Optional[User]:
        row = _execute_query(
            "SELECT id, username, is_admin FROM users WHERE id = %s", (user_id,), fetch_one=True
        )
        return _user(row) if row else None

    @staticmethod
    def by_token(token: str) -> Optional[User]:
        row = _execute_query(
            (
                "SELECT u.id, u.username, u.is_admin FROM sessions s "
                "JOIN users u ON u.id = s.user_id WHERE s.token_hash = %s"
            ),
            (hash_token(token),),
            fetch_one=True,
        )
        return _user(row) if row else None


class AccessRepository:
    """Per-Collection roles. Administrators implicitly hold every role on every Collection."""

    @staticmethod
    def grant(user_id: int, collection_id: int, role: Role) -> None:
        _execute_query(
            (
                "INSERT INTO collection_grants (user_id, collection_id, role) VALUES (%s, %s, %s) "
                "ON CONFLICT (user_id, collection_id) DO UPDATE SET role = EXCLUDED.role "
                "RETURNING role"
            ),
            (user_id, collection_id, role),
            fetch_one=True,
        )

    @staticmethod
    def revoke(user_id: int, collection_id: int) -> None:
        _execute_query(
            (
                "DELETE FROM collection_grants WHERE user_id = %s AND collection_id = %s "
                "RETURNING role"
            ),
            (user_id, collection_id),
        )

    @staticmethod
    def role(user: User, collection_id: int) -> Optional[Role]:
        """The user's role on an existing Collection, or None if they have no access."""
        if user.is_admin:
            return "editor" if CollectionRepository.get_by_id(collection_id) else None
        row = _execute_query(
            "SELECT role FROM collection_grants WHERE user_id = %s AND collection_id = %s",
            (user.id, collection_id),
            fetch_one=True,
        )
        return cast(Role, row[0]) if row else None

    @staticmethod
    def accessible_collections(user: User) -> list[Collection]:
        if user.is_admin:
            return CollectionRepository.list_all()
        rows = _execute_query(
            (
                "SELECT c.id, c.name FROM collections c "
                "JOIN collection_grants g ON g.collection_id = c.id "
                "WHERE g.user_id = %s ORDER BY c.id"
            ),
            (user.id,),
        )
        return [_collection(row) for row in rows]
