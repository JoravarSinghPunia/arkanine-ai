"""Uploading each supported file type, and rejecting the ones Arkanine can't read."""

import io

import docx
import httpx
import pytest

QUESTION = {"question": "What causes tides?"}


def _pdf(*lines: str) -> bytes:
    """A one-page PDF with `lines` as real text; with no lines it has no text layer."""
    text = " 0 -16 Td ".join(f"({line}) Tj" for line in lines)
    stream = f"BT /F1 12 Tf 72 720 Td {text} ET".encode() if lines else b""
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    pdf = b"%PDF-1.4\n"
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf += b"%d 0 obj\n%s\nendobj\n" % (number, body)
    xref = len(pdf)
    pdf += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    pdf += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    pdf += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        xref,
    )
    return pdf


def _upload(api: httpx.Client, collection_id: int, filename: str, data: bytes) -> httpx.Response:
    return api.post(
        f"/collections/{collection_id}/documents/upload", files={"file": (filename, data)}
    )


def _cited(api: httpx.Client, collection_id: int) -> list[str]:
    answer = api.post(f"/collections/{collection_id}/answer", json=QUESTION).json()
    return [citation["text"] for citation in answer["citations"]]


def test_an_html_page_is_answerable_from_its_visible_text(
    api: httpx.Client, collection_id: int
) -> None:
    html = b"""<!doctype html><html><head><title>Tides</title>
    <style>p { color: tides; }</style><script>var tides = "caused by script";</script></head>
    <body><h1>Tides</h1><p>Tides are caused by the <b>Moon</b>.</p><p>Waves are wind.</p>
    </body></html>"""

    uploaded = _upload(api, collection_id, "tides.html", html)

    assert uploaded.status_code == 201
    assert _cited(api, collection_id) == ["Tides are caused by the Moon."]


def test_a_word_document_is_answerable_including_its_tables(
    api: httpx.Client, collection_id: int
) -> None:
    document = docx.Document()
    document.add_heading("Ocean notes", level=1)
    document.add_paragraph("Waves are made by wind.")
    document.add_table(rows=1, cols=1).cell(0, 0).text = "Tides are caused by the Moon."
    data = io.BytesIO()
    document.save(data)

    uploaded = _upload(api, collection_id, "ocean.docx", data.getvalue())

    assert uploaded.status_code == 201
    assert _cited(api, collection_id) == ["Tides are caused by the Moon."]


def test_a_text_pdf_is_answerable(api: httpx.Client, collection_id: int) -> None:
    pdf = _pdf("Waves are made by wind.", "Tides are caused by the Moon.")

    uploaded = _upload(api, collection_id, "ocean.pdf", pdf)

    assert uploaded.status_code == 201
    assert _cited(api, collection_id) == ["Tides are caused by the Moon."]


def test_a_scanned_pdf_without_a_text_layer_is_rejected_as_scanned(
    api: httpx.Client, collection_id: int
) -> None:
    response = _upload(api, collection_id, "scan.pdf", _pdf())

    assert response.status_code == 422
    assert "scan.pdf" in response.json()["detail"]
    assert "scanned" in response.json()["detail"]


@pytest.mark.parametrize(
    ("filename", "category"),
    [
        ("budget.xlsx", "spreadsheet"),
        ("budget.xls", "spreadsheet"),
        ("budget.csv", "spreadsheet"),
        ("budget.ods", "spreadsheet"),
        ("message.eml", "email"),
        ("message.msg", "email"),
        ("inbox.mbox", "email"),
        ("page.png", "scanned"),
        ("page.jpg", "scanned"),
        ("page.tiff", "scanned"),
    ],
)
def test_spreadsheets_email_and_scanned_images_are_explicitly_rejected(
    api: httpx.Client, collection_id: int, filename: str, category: str
) -> None:
    response = _upload(api, collection_id, filename, b"anything")

    assert response.status_code == 415
    assert filename in response.json()["detail"]
    assert category in response.json()["detail"]


@pytest.mark.parametrize("filename", ["broken.pdf", "broken.docx"])
def test_a_corrupt_pdf_or_word_document_is_reported_unreadable(
    api: httpx.Client, collection_id: int, filename: str
) -> None:
    response = _upload(api, collection_id, filename, b"%PDF-1.7 PK not really a document")

    assert response.status_code == 422
    assert filename in response.json()["detail"]
