"""Split documents into citable passages."""

import re
from dataclasses import dataclass

from arkanine.models import Document

# A passage ends at sentence punctuation followed by whitespace, or at a blank line.
_BOUNDARY = re.compile(r"(?<=[.!?])\s+|\n\s*\n")


@dataclass(frozen=True)
class Passage:
    """A span of a document that an answer can cite."""

    document: Document
    start_offset: int
    end_offset: int

    @property
    def text(self) -> str:
        return self.document.content[self.start_offset : self.end_offset]


def passage_spans(content: str) -> list[tuple[int, int]]:
    """Split text into sentence-sized passages, as (start, end) offsets into it."""
    spans: list[tuple[int, int]] = []
    start = 0
    for boundary in _BOUNDARY.finditer(content):
        _append_trimmed(content, start, boundary.start(), spans)
        start = boundary.end()
    _append_trimmed(content, start, len(content), spans)
    return spans


def _append_trimmed(content: str, start: int, end: int, spans: list[tuple[int, int]]) -> None:
    span = content[start:end]
    if not span.strip():
        return
    start += len(span) - len(span.lstrip())
    end -= len(span) - len(span.rstrip())
    spans.append((start, end))
