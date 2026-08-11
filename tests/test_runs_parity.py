"""the browser path and the cli path must agree.

the browser extracts positioned text runs with pdf.js and hands them to the
same python parser. here the runs are produced from pymupdf spans, which have
the same shape pdf.js emits, and the resulting parse is held to the same
expected output as the file path. if the two paths drift apart, this fails.
"""

import json
from pathlib import Path

import pymupdf
import pytest

from vault.syllabus.pipeline import parse_extracted
from vault.text.runs import document_from_runs

FIXTURES = Path(__file__).parent / "fixtures" / "syllabi"
EXPECTED = Path(__file__).parent / "expected"

NAMES = ["structure-a-bulleted", "structure-b-table", "structure-c-labelled"]


def runs_payload(path: Path) -> dict:
    """what the javascript extractor would send, built from pymupdf spans."""
    doc = pymupdf.open(path)
    pages = []
    for index, page in enumerate(doc):
        runs = []
        for block in page.get_text("dict")["blocks"]:
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    x0, y0, x1, y1 = span["bbox"]
                    runs.append(
                        {
                            "text": span["text"],
                            "x": x0,
                            "y": y0,
                            "w": x1 - x0,
                            "h": y1 - y0,
                            "size": span.get("size", 0),
                        }
                    )
        pages.append(
            {
                "number": index + 1,
                "width": page.rect.width,
                "height": page.rect.height,
                "runs": runs,
            }
        )
    doc.close()
    return {"pages": pages, "filename": path.name, "sha256": "test"}


@pytest.fixture(scope="module", params=NAMES)
def case(request):
    payload = runs_payload(FIXTURES / f"{request.param}.pdf")
    # round trip through json, exactly as the browser boundary does
    payload = json.loads(json.dumps(payload))
    parsed = parse_extracted(document_from_runs(payload))
    expected = json.loads((EXPECTED / f"{request.param}.json").read_text(encoding="utf-8"))
    return parsed, expected


class TestRunsPathMatchesExpectations:
    def test_structure(self, case):
        parsed, expected = case
        assert parsed.structure == expected["structure"]

    def test_course_identity(self, case):
        parsed, expected = case
        assert parsed.course.code == expected["course"]["code"]
        assert parsed.course.term.name == expected["course"]["term"]
        assert parsed.course.term.year == expected["course"]["year"]

    def test_session_count(self, case):
        parsed, expected = case
        assert len(parsed.sessions) == expected["session_count"]

    def test_reading_counts_exact(self, case):
        parsed, expected = case
        for week, want in expected["reading_counts"].items():
            got = sum(len(s.readings) for s in parsed.sessions if s.week_number == int(week))
            assert got == want, f"week {week}: expected {want}, parsed {got}"

    def test_ai_stance(self, case):
        parsed, expected = case
        assert parsed.ai_stance == expected["ai_stance"]

    def test_weight_total(self, case):
        parsed, expected = case
        assert parsed.deliverables.weight_total == expected["weight_total"]


class TestRunsScanned:
    def test_scanned_page_is_flagged_not_invented(self):
        payload = runs_payload(Path(__file__).parent / "fixtures" / "readings" / "scanned.pdf")
        doc = document_from_runs(json.loads(json.dumps(payload)))
        assert doc.status == "needs_ocr"
        assert doc.pages[0].had_text_layer is False
