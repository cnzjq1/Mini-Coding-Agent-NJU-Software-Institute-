"""Local extraction of project requirements from text, PDF, and Word files."""

from __future__ import annotations

import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree


WORD_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
MAX_INPUT_BYTES = 25 * 1024 * 1024
MAX_XML_BYTES = 12 * 1024 * 1024


def _clean(text: str) -> str:
    text = text.replace("\x00", "")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _read_pdf(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError("PDF support requires: pip install pypdf") from exc
    try:
        reader = PdfReader(str(path))
        if reader.is_encrypted and reader.decrypt("") == 0:
            raise ValueError("Password-protected PDF is not supported")
        pages = []
        for number, page in enumerate(reader.pages, 1):
            text = _clean(page.extract_text() or "")
            if text:
                pages.append(f"[PDF page {number}]\n{text}")
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"Cannot read PDF: {exc}") from exc
    if not pages:
        raise ValueError("PDF contains no extractable text; OCR is required for scanned pages")
    return "\n\n".join(pages)


def _paragraph_text(element: ElementTree.Element) -> str:
    return "".join(node.text or "" for node in element.iter(WORD_NS + "t")).strip()


def _read_docx(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as archive:
            info = archive.getinfo("word/document.xml")
            if info.file_size > MAX_XML_BYTES:
                raise ValueError("Word document XML is too large")
            root = ElementTree.fromstring(archive.read(info))
    except (KeyError, zipfile.BadZipFile, ElementTree.ParseError) as exc:
        raise ValueError(f"Invalid Word .docx file: {exc}") from exc

    body = root.find(".//" + WORD_NS + "body")
    if body is None:
        raise ValueError("Word document has no body")
    blocks: list[str] = []
    for child in body:
        if child.tag == WORD_NS + "p":
            text = _paragraph_text(child)
            if text:
                blocks.append(text)
        elif child.tag == WORD_NS + "tbl":
            rows = []
            for row in child.findall("./" + WORD_NS + "tr"):
                cells = [_paragraph_text(cell) for cell in row.findall("./" + WORD_NS + "tc")]
                if any(cells):
                    rows.append(" | ".join(cells))
            if rows:
                blocks.append("[Word table]\n" + "\n".join(rows))
    result = _clean("\n\n".join(blocks))
    if not result:
        raise ValueError("Word document contains no extractable text")
    return result


def load_requirement_file(filename: str | Path, max_chars: int = 300000) -> str:
    path = Path(filename).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Requirement file not found: {path}")
    if path.stat().st_size > MAX_INPUT_BYTES:
        raise ValueError(f"Requirement file exceeds {MAX_INPUT_BYTES // 1024 // 1024} MB")
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        content = _read_pdf(path)
    elif suffix == ".docx":
        content = _read_docx(path)
    elif suffix in {".txt", ".md"}:
        content = _clean(path.read_text(encoding="utf-8-sig"))
    elif suffix == ".doc":
        raise ValueError("Legacy .doc is not supported; save it as .docx first")
    else:
        raise ValueError("Supported requirement formats: .pdf, .docx, .txt, .md")
    if not content:
        raise ValueError("Requirement file is empty")
    if len(content) > max_chars:
        raise ValueError(f"Extracted requirement exceeds {max_chars} characters")
    return f"[Requirement source: {path.name}]\n\n{content}"
