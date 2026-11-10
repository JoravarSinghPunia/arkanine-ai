"""Domain models for Collections and Documents."""

from dataclasses import dataclass
from typing import Literal

# What a user may do in one Collection; an editor can do everything a reader can.
Role = Literal["reader", "editor"]


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
class User:
    """A local account. Administrators can access every Collection."""

    id: int
    username: str
    is_admin: bool
