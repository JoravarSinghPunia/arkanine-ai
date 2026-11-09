"""Repository layer for database operations."""
import os
from typing import Optional

import psycopg

from arkanine.models import Collection, Document


class CollectionRepository:
    """Repository for Collection operations."""

    @staticmethod
    def create(name: str) -> Collection:
        """Create a new collection."""
        with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO collections (name) VALUES (%s) RETURNING id, name",
                    (name,),
                )
                row = cur.fetchone()
                conn.commit()
        if not row:
            raise RuntimeError("Failed to create collection")
        return Collection(id=row[0], name=row[1])

    @staticmethod
    def get_by_id(collection_id: int) -> Optional[Collection]:
        """Get a collection by ID."""
        with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, name FROM collections WHERE id = %s",
                    (collection_id,),
                )
                row = cur.fetchone()
        if not row:
            return None
        return Collection(id=row[0], name=row[1])


class DocumentRepository:
    """Repository for Document operations."""

    @staticmethod
    def create(collection_id: int, title: str, content: str) -> Document:
        """Create a new document in a collection."""
        with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    (
                        "INSERT INTO documents (collection_id, title, content) "
                        "VALUES (%s, %s, %s) "
                        "RETURNING id, collection_id, title, content"
                    ),
                    (collection_id, title, content),
                )
                row = cur.fetchone()
                conn.commit()
        if not row:
            raise RuntimeError("Failed to create document")
        return Document(
            id=row[0], collection_id=row[1], title=row[2], content=row[3]
        )

    @staticmethod
    def get_by_collection(collection_id: int) -> list[Document]:
        """Get all documents in a collection."""
        with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    (
                        "SELECT id, collection_id, title, content FROM documents "
                        "WHERE collection_id = %s ORDER BY id"
                    ),
                    (collection_id,),
                )
                rows = cur.fetchall()
        return [
            Document(id=row[0], collection_id=row[1], title=row[2], content=row[3])
            for row in rows
        ]
