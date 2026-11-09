"""Split documents into citable passages and find the ones relevant to a question."""

import re
from dataclasses import dataclass

from arkanine.models import Document

# A passage ends at sentence punctuation followed by whitespace, or at a blank line.
_BOUNDARY = re.compile(r"(?<=[.!?])\s+|\n\s*\n")
_WORD = re.compile(r"[a-z0-9]+")
_STOPWORDS = frozenset(
    """
    a about above after again against all am an and any are as at be because been before
    being below between both but by can could did do does doing down during each few for
    from further had has have having he her here hers him his how i if in into is it its
    me more most my no nor not of off on once only or other our out over own same she
    should so some such than that the their them then there these they this those through
    to too under until up very was we were what when where which while who whom why will
    with would you your
    """.split()
)


@dataclass(frozen=True)
class Passage:
    """A span of a document that an answer can cite."""

    document: Document
    start_offset: int
    end_offset: int

    @property
    def text(self) -> str:
        return self.document.content[self.start_offset : self.end_offset]


def split_into_passages(document: Document) -> list[Passage]:
    """Split a document into sentence-sized passages with offsets into its content."""
    passages: list[Passage] = []
    start = 0
    for boundary in _BOUNDARY.finditer(document.content):
        _append_trimmed(document, start, boundary.start(), passages)
        start = boundary.end()
    _append_trimmed(document, start, len(document.content), passages)
    return passages


def _append_trimmed(document: Document, start: int, end: int, passages: list[Passage]) -> None:
    span = document.content[start:end]
    if not span.strip():
        return
    start += len(span) - len(span.lstrip())
    end -= len(span) - len(span.rstrip())
    passages.append(Passage(document, start, end))


def _stem(word: str) -> str:
    """Crudely strip common English suffixes so "causes" matches "caused"."""
    for suffix in ("ing", "es", "ed", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[: -len(suffix)]
    return word


def _terms(text: str) -> set[str]:
    return {_stem(word) for word in _WORD.findall(text.lower()) if word not in _STOPWORDS}


def find_relevant_passages(
    documents: list[Document], question: str, limit: int = 8
) -> list[Passage]:
    """Return the passages sharing the most terms with the question, best first.

    Passages sharing no terms with the question are never returned, so an empty
    result means the documents do not contain an answer.
    """
    question_terms = _terms(question)
    scored = [
        (len(question_terms & _terms(passage.text)), index, passage)
        for index, passage in enumerate(
            passage for document in documents for passage in split_into_passages(document)
        )
    ]
    relevant = [entry for entry in scored if entry[0] > 0]
    relevant.sort(key=lambda entry: (-entry[0], entry[1]))
    return [passage for _, _, passage in relevant[:limit]]
