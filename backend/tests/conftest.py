import io
import atexit
import os
import shutil
import tempfile
import zipfile
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]

# Knowledge rebuilds write chunks into KNOWLEDGE_DIR/chunks. Tests must never
# touch the real index, so work on a throwaway copy of the corpus instead.
_REAL_KNOWLEDGE_DIR = BACKEND_DIR / "data" / "knowledge"
_TEST_KNOWLEDGE_DIR = Path(tempfile.mkdtemp(prefix="safety-hazard-knowledge-"))
if _REAL_KNOWLEDGE_DIR.exists():
    shutil.copytree(_REAL_KNOWLEDGE_DIR, _TEST_KNOWLEDGE_DIR, dirs_exist_ok=True)
atexit.register(shutil.rmtree, _TEST_KNOWLEDGE_DIR, ignore_errors=True)

os.environ["PROVIDER_MODE"] = "mock"
os.environ["DATABASE_URL"] = f"sqlite:///{(BACKEND_DIR / 'data' / 'test.db').as_posix()}"
os.environ["UPLOAD_DIR"] = str(BACKEND_DIR / "data" / "uploads" / "test")
os.environ["KNOWLEDGE_DIR"] = str(_TEST_KNOWLEDGE_DIR)
os.environ["FAISS_INDEX_DIR"] = str(BACKEND_DIR / "data" / "faiss" / "test")
os.environ["MAX_FOLLOWUPS"] = "2"


def _build_pdf(text: str) -> bytes:
    """Build a minimal single-page PDF containing ``text`` (ASCII only)."""
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
    ]
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode("ascii")
    objects.append(
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream"
    )
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    buf = io.BytesIO()
    buf.write(b"%PDF-1.4\n")
    offsets = []
    for index, body in enumerate(objects, start=1):
        offsets.append(buf.tell())
        buf.write(f"{index} 0 obj\n".encode())
        buf.write(body)
        buf.write(b"\nendobj\n")
    xref_at = buf.tell()
    buf.write(f"xref\n0 {len(objects) + 1}\n".encode())
    buf.write(b"0000000000 65535 f \n")
    for offset in offsets:
        buf.write(f"{offset:010d} 00000 n \n".encode())
    buf.write(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_at}\n%%EOF\n".encode()
    )
    return buf.getvalue()


def _build_docx(text: str) -> bytes:
    """Build a minimal valid .docx containing one paragraph of ``text``."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Default Extension="rels" '
            'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Override PartName="/word/document.xml" ContentType="application/vnd.'
            'openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            "</Types>",
        )
        archive.writestr(
            "_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/'
            '2006/relationships/officeDocument" Target="word/document.xml"/>'
            "</Relationships>",
        )
        archive.writestr(
            "word/document.xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            "<w:body><w:p><w:r><w:t>"
            + text
            + "</w:t></w:r></w:p></w:body></w:document>",
        )
    return buf.getvalue()


@pytest.fixture
def make_pdf():
    return _build_pdf


@pytest.fixture
def make_docx():
    return _build_docx
