"""Domain models for Collections and Documents."""
from dataclasses import dataclass


@dataclass
class Collection:
    """A named set of documents."""

    id: int
    name: str


@dataclass
class Document:
    """A document ingested into a collection."""

    id: int
    collection_id: int
    title: str
    content: str


@dataclass
class Citation:
    """A citation pointing to a source passage."""

    document_id: int
    text: str


@dataclass
class Answer:
    """An answer with citations."""

    answer: str
    citations: list[Citation]
