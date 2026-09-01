import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from coding_agent.requirements import load_requirement_file


DOCX_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p><w:r><w:t>Build a task API</w:t></w:r></w:p>
    <w:tbl>
      <w:tr><w:tc><w:p><w:r><w:t>Feature</w:t></w:r></w:p></w:tc>
      <w:tc><w:p><w:r><w:t>Required</w:t></w:r></w:p></w:tc></w:tr>
      <w:tr><w:tc><w:p><w:r><w:t>Tests</w:t></w:r></w:p></w:tc>
      <w:tc><w:p><w:r><w:t>Yes</w:t></w:r></w:p></w:tc></w:tr>
    </w:tbl>
    <w:sectPr/>
  </w:body>
</w:document>"""


class RequirementFileTests(unittest.TestCase):
    def test_docx_extracts_paragraphs_and_tables(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "requirement.docx"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("word/document.xml", DOCX_XML)
            result = load_requirement_file(path)
            self.assertIn("Build a task API", result)
            self.assertIn("Feature | Required", result)
            self.assertIn("Tests | Yes", result)

    def test_pdf_preserves_page_markers(self):
        class Page:
            def __init__(self, text):
                self.text = text

            def extract_text(self):
                return self.text

        class Reader:
            is_encrypted = False
            pages = [Page("first requirement"), Page("second requirement")]

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "requirement.pdf"
            path.write_bytes(b"fake")
            fake_module = SimpleNamespace(PdfReader=lambda filename: Reader())
            with patch.dict(sys.modules, {"pypdf": fake_module}):
                result = load_requirement_file(path)
            self.assertIn("[PDF page 1]", result)
            self.assertIn("[PDF page 2]", result)

    def test_scanned_pdf_reports_ocr_requirement(self):
        reader = SimpleNamespace(
            is_encrypted=False,
            pages=[SimpleNamespace(extract_text=lambda: "")],
        )
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "scan.pdf"
            path.write_bytes(b"fake")
            with patch.dict(sys.modules, {"pypdf": SimpleNamespace(PdfReader=lambda filename: reader)}):
                with self.assertRaisesRegex(ValueError, "OCR"):
                    load_requirement_file(path)

    def test_legacy_doc_has_actionable_error(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "old.doc"
            path.write_bytes(b"old")
            with self.assertRaisesRegex(ValueError, "save it as .docx"):
                load_requirement_file(path)

    def test_extracted_character_limit(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "large.txt"
            path.write_text("abcdef", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "exceeds 5"):
                load_requirement_file(path, max_chars=5)


if __name__ == "__main__":
    unittest.main()
