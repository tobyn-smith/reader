"""reading pdfs with hostile layouts: columns, footnotes, no text layer."""

import shutil
from pathlib import Path

import pytest

from vault.text.chunk import chunk_document
from vault.text.extract import extract_document

READINGS = Path(__file__).parent / "fixtures" / "readings"


class TestTwoColumn:
    def test_columns_are_not_interleaved(self):
        doc = extract_document(READINGS / "two-column.pdf")
        text = doc.pages[0].text
        # each column reads as a contiguous run. interleaving would place a
        # fragment of the right column inside this left column sentence.
        assert "the shadow of that future disciplines present behaviour" in text.replace(
            "\n", " "
        )
        assert "change what actors believe about one another" in text.replace("\n", " ")

    def test_column_count_detected(self):
        doc = extract_document(READINGS / "two-column.pdf")
        assert doc.pages[0].column_count == 2


class TestFootnotes:
    def test_footnotes_split_from_body(self):
        doc = extract_document(READINGS / "footnote-heavy.pdf")
        page = doc.pages[0]
        assert page.footnotes, "footnote block was not separated"
        assert "Invented Archive" in " ".join(page.footnotes)
        assert "Invented Archive" not in page.text

    def test_footnote_chunks_keep_kind_and_marker(self):
        doc = extract_document(READINGS / "footnote-heavy.pdf")
        notes = [c for c in chunk_document(doc) if c.kind == "footnote"]
        assert notes
        assert notes[0].ref_marker == "1"

    def test_chunks_carry_page_numbers(self):
        doc = extract_document(READINGS / "footnote-heavy.pdf")
        chunks = chunk_document(doc)
        assert chunks
        assert all(c.page_number >= 1 for c in chunks)
        assert any(c.page_number == 2 for c in chunks)


class TestScanned:
    def test_missing_text_layer_is_reported_not_papered_over(self):
        doc = extract_document(READINGS / "scanned.pdf", ocr="never")
        assert doc.pages[0].had_text_layer is False
        assert doc.status == "needs_ocr"
        assert doc.pages[0].text.strip() == ""

    @pytest.mark.skipif(shutil.which("ocrmypdf") is None, reason="ocrmypdf not installed")
    def test_ocr_recovers_text_and_flags_it(self):
        doc = extract_document(READINGS / "scanned.pdf", ocr="always")
        assert doc.ocr_used is True
        assert "Invented Prose" in doc.text
