"""Database initialization and schema."""

import os

import psycopg


def create_schema() -> None:
    """Create the database schema for collections and documents."""
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        with conn.cursor() as cur:
            # Collections table
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS collections (
                    id SERIAL PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            # Documents table
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS documents (
                    id SERIAL PRIMARY KEY,
                    collection_id INTEGER NOT NULL REFERENCES collections(id),
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            # A failed upload is kept, without content, so its reason can be listed.
            cur.execute(
                """
                ALTER TABLE documents
                    ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'ready'
                        CHECK (status IN ('ready', 'failed')),
                    ADD COLUMN IF NOT EXISTS error TEXT
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    username TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    is_admin BOOLEAN NOT NULL DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            # Only a hash of each bearer token is stored.
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS collection_grants (
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    collection_id INTEGER NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
                    role TEXT NOT NULL CHECK (role IN ('reader', 'editor')),
                    PRIMARY KEY (user_id, collection_id)
                )
                """
            )
            conn.commit()
