"""Turn an uploaded file into document text.

Each supported file type has an extractor keyed by extension. Markdown and plain text
are stored verbatim; further formats (PDF, DOCX, HTML) plug in here.
"""

from collections.abc import Callable
from pathlib import PurePath


class UnsupportedFileType(Exception):
    """No extractor exists for this file type."""


class UnreadableFile(Exception):
    """The file has a supported type but its text could not be read."""


def _decode_utf8(data: bytes) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise UnreadableFile("not valid UTF-8 text") from error


_EXTRACTORS: dict[str, Callable[[bytes], str]] = {
    ".md": _decode_utf8,
    ".markdown": _decode_utf8,
    ".txt": _decode_utf8,
}

SUPPORTED_EXTENSIONS = tuple(sorted(_EXTRACTORS))


def extract_text(filename: str, data: bytes) -> str:
    extractor = _EXTRACTORS.get(PurePath(filename).suffix.lower())
    if extractor is None:
        raise UnsupportedFileType(filename)
    return extractor(data)
