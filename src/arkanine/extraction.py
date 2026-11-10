"""Turn an uploaded file into document text.

Each supported file type has an extractor keyed by extension. Markdown and plain text
are stored verbatim; HTML, DOCX and PDF are reduced to their text, one paragraph per
blank-line-separated block, so passages and citation offsets refer to the stored text.
"""

import io
import re
import zipfile
from collections.abc import Callable, Iterable, Iterator
from pathlib import PurePath

import docx
import pypdf
from bs4 import BeautifulSoup
from docx.table import Table
from pypdf.generic import ContentStream

MAX_UPLOAD_BYTES = 25 * 1024 * 1024
# A DOCX is a zip; its entries may not expand past this. zipfile stops reading each
# entry at its declared size, so declared sizes can't be used to smuggle more.
_MAX_DOCX_EXPANDED_BYTES = 100 * 1024 * 1024


class UnsupportedFileType(Exception):
    """No extractor exists for this file type. The message says why."""


class UnreadableFile(Exception):
    """The file has a supported type but its text could not be read."""


def check_document_text(text: str) -> str:
    """Reject text that can't be stored or could never be cited."""
    if "\x00" in text:
        raise UnreadableFile("contains a null character")
    if not text.strip():
        raise UnreadableFile("contains no text")
    return text


def _decode_utf8(data: bytes) -> str:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise UnreadableFile("not valid UTF-8 text") from error
    return check_document_text(text)


_HTML_NON_CONTENT = ("head", "script", "style", "noscript", "template", "svg")
_HTML_BLOCKS = (
    "address", "article", "aside", "blockquote", "caption", "dd", "div", "dt",
    "figcaption", "footer", "h1", "h2", "h3", "h4", "h5", "h6", "header", "li",
    "main", "nav", "p", "pre", "section", "td", "th", "tr",
)  # fmt: skip


def _paragraphs(blocks: Iterable[str]) -> str:
    """Join blocks as blank-line-separated paragraphs, collapsing whitespace inside each.

    A blank line inside a block also starts a new paragraph.
    """
    paragraphs = (
        " ".join(part.split()) for block in blocks for part in re.split(r"\n\s*\n", block)
    )
    return check_document_text("\n\n".join(p for p in paragraphs if p))


def _extract_html(data: bytes) -> str:
    soup = BeautifulSoup(data, "html.parser")
    for element in soup(_HTML_NON_CONTENT):
        element.decompose()
    for element in soup(_HTML_BLOCKS):
        element.insert_before("\n\n")
        element.insert_after("\n\n")
    for element in soup("br"):
        element.replace_with("\n\n")
    return _paragraphs([soup.get_text()])


def _docx_blocks(document: "docx.document.Document") -> Iterator[str]:
    """Yield paragraph and table-cell text in document order."""
    for item in document.iter_inner_content():
        if isinstance(item, Table):
            # A merged cell is returned once per grid position it spans. Holding the
            # elements keeps lxml's proxies alive, so identity comparison is stable.
            seen: list[object] = []
            for row in item.rows:
                for cell in row.cells:
                    if not any(cell._tc is element for element in seen):
                        seen.append(cell._tc)
                        yield cell.text
        else:
            yield item.text


def _check_docx_expansion(data: bytes) -> None:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            expanded = sum(entry.file_size for entry in archive.infolist())
    except zipfile.BadZipFile as error:
        raise UnreadableFile("not a readable Word document") from error
    if expanded > _MAX_DOCX_EXPANDED_BYTES:
        raise UnreadableFile(f"expands to more than {_MAX_DOCX_EXPANDED_BYTES // (1024 * 1024)} MB")


def _extract_docx(data: bytes) -> str:
    _check_docx_expansion(data)
    try:
        document = docx.Document(io.BytesIO(data))
        blocks = list(_docx_blocks(document))
    except Exception as error:  # a corrupt file can fail anywhere inside the parser
        raise UnreadableFile("not a readable Word document") from error
    return _paragraphs(blocks)


def _draws_image(page: pypdf.PageObject) -> bool:
    """Whether the page's content draws an image, as a scanned page does.

    Resources are often shared between pages, so an image merely being available to a
    page doesn't mean the page shows it.
    """
    resources = page.get("/Resources")
    xobjects = resources.get_object().get("/XObject") if resources else None
    contents = page.get_contents()
    if not xobjects or contents is None:
        return False
    xobjects = xobjects.get_object()
    for operands, operator in ContentStream(contents, page.pdf).operations:
        if operator == b"Do" and operands and operands[0] in xobjects:
            if xobjects[operands[0]].get_object().get("/Subtype") == "/Image":
                return True
    return False


def _extract_pdf(data: bytes) -> str:
    try:
        reader = pypdf.PdfReader(io.BytesIO(data))
        # Many PDFs are encrypted with an empty user password and open without one.
        if reader.is_encrypted and not reader.decrypt(""):
            raise UnreadableFile("is password-protected")
        pages = [page.extract_text() for page in reader.pages]
        scanned = [
            number
            for number, (page, text) in enumerate(zip(reader.pages, pages), start=1)
            if not text.strip() and _draws_image(page)
        ]
    except UnreadableFile:
        raise
    except Exception as error:  # a corrupt file can fail anywhere inside the parser
        raise UnreadableFile("not a readable PDF") from error
    if not any(page.strip() for page in pages):
        raise UnreadableFile(_SCANNED)
    # Ingesting the rest would silently drop the scanned pages' content.
    if scanned:
        listed = ", ".join(str(number) for number in scanned)
        raise UnreadableFile(f"page {listed} {_SCANNED}")
    return _paragraphs(pages)


_EXTRACTORS: dict[str, Callable[[bytes], str]] = {
    ".pdf": _extract_pdf,
    ".docx": _extract_docx,
    ".htm": _extract_html,
    ".html": _extract_html,
    ".md": _decode_utf8,
    ".markdown": _decode_utf8,
    ".txt": _decode_utf8,
}

SUPPORTED_EXTENSIONS = tuple(sorted(_EXTRACTORS))

_SCANNED = "has no text layer; scanned documents are not supported"
_SPREADSHEET = "spreadsheets are not supported"
_EMAIL = "email is not supported"
_IMAGE = "images and scanned documents are not supported"

# Out of scope for the MVP (see #1), so they get a reason rather than a generic refusal.
_REJECTED: dict[str, str] = {
    **dict.fromkeys((".csv", ".ods", ".tsv", ".xls", ".xlsm", ".xlsx"), _SPREADSHEET),
    **dict.fromkeys((".eml", ".mbox", ".msg"), _EMAIL),
    **dict.fromkeys(
        (".bmp", ".gif", ".heic", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"), _IMAGE
    ),
}


def extract_text(filename: str, data: bytes) -> str:
    extension = PurePath(filename).suffix.lower()
    extractor = _EXTRACTORS.get(extension)
    if extractor is None:
        raise UnsupportedFileType(_REJECTED.get(extension, "unsupported file type"))
    return extractor(data)
