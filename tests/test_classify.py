"""a visitor drops a pile of pdfs, not two tidy piles.

if this gets it wrong the tool asks them to sort their own files, which is the
job it exists to do, so both directions are checked.
"""

from pathlib import Path

import pytest

from vault.classify import READING, SYLLABUS, classify
from vault.text.extract import extract_document

FIXTURES = Path(__file__).parent / "fixtures"

SYLLABI = sorted((FIXTURES / "syllabi").glob("*.pdf"))
READINGS = sorted((FIXTURES / "readings").glob("*.pdf"))


@pytest.mark.parametrize("path", SYLLABI, ids=lambda p: p.stem)
def test_syllabi_are_recognised(path):
    assert classify(extract_document(path)).kind == SYLLABUS


@pytest.mark.parametrize("path", READINGS, ids=lambda p: p.stem)
def test_readings_are_recognised(path):
    assert classify(extract_document(path)).kind == READING


def test_a_scanned_page_with_no_text_is_not_called_a_syllabus():
    # nothing to read means nothing to claim. defaulting to syllabus would send
    # an empty document into the schedule parser.
    verdict = classify(extract_document(FIXTURES / "readings" / "scanned.pdf"))
    assert verdict.kind == READING


def test_the_verdict_explains_itself():
    verdict = classify(extract_document(SYLLABI[0]))
    assert verdict.reasons, "a classification with no stated reason cannot be checked"
    assert 0.0 <= verdict.confidence <= 1.0
