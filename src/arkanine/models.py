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
