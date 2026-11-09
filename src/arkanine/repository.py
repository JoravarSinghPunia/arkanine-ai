"""Repository layer for database operations."""

import os
from typing import Any, Optional

import psycopg

from arkanine.models import Collection, Document


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
        return Collection(id=row[0], name=row[1])

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
        return Collection(id=row[0], name=row[1])


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
        return Document(id=row[0], collection_id=row[1], title=row[2], content=row[3])

    @staticmethod
    def get(collection_id: int, document_id: int) -> Optional[Document]:
        """Get a document by ID, only if it belongs to the given collection."""
        row = _execute_query(
            (
                "SELECT id, collection_id, title, content FROM documents "
                "WHERE collection_id = %s AND id = %s"
            ),
            (collection_id, document_id),
            fetch_one=True,
        )
        if not row:
            return None
        return Document(id=row[0], collection_id=row[1], title=row[2], content=row[3])

    @staticmethod
    def get_by_collection(collection_id: int) -> list[Document]:
        """Get all documents in a collection."""
        rows = _execute_query(
            (
                "SELECT id, collection_id, title, content FROM documents "
                "WHERE collection_id = %s ORDER BY id"
            ),
            (collection_id,),
        )
        return [
            Document(id=row[0], collection_id=row[1], title=row[2], content=row[3]) for row in rows
        ]
