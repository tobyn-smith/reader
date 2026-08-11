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


class TestWebEntryPoints:
    """the browser calls these across a json boundary, so exercise them as json."""

    def test_parse_runs_returns_the_same_counts(self):
        from vault import web

        payload = runs_payload(FIXTURES / "structure-a-bulleted.pdf")
        result = json.loads(web.parse_runs(json.dumps(payload)))
        expected = json.loads(
            (EXPECTED / "structure-a-bulleted.json").read_text(encoding="utf-8")
        )
        assert result["structure"] == expected["structure"]
        assert len(result["sessions"]) == expected["session_count"]
        for week, want in expected["reading_counts"].items():
            got = sum(
                len(s["readings"]) for s in result["sessions"] if s["week_number"] == int(week)
            )
            assert got == want, f"week {week}"

    def test_match_reading_scores_across_the_boundary(self):
        from vault import web

        candidates = json.dumps(
            [
                {
                    "id": "w1",
                    "title": "Rationalist Accounts of Bargaining Failure",
                    "year": 1995,
                    "authors": [{"surname": "Okonkwo", "given": "Adaeze N."}],
                    "doi": None,
                },
                {"id": "w2", "title": "Something Entirely Different", "year": 2010,
                 "authors": [{"surname": "Nobody"}], "doi": None},
            ]
        )
        head = "Rationalist Accounts of Bargaining Failure\nAdaeze N. Okonkwo\n1995"
        result = json.loads(web.match_reading(head, candidates))
        assert result["id"] == "w1"
        assert result["score"] > 0.9

    def test_match_reports_no_match_rather_than_guessing(self):
        from vault import web

        candidates = json.dumps(
            [{"id": "w1", "title": "Wholly Unrelated Title", "year": 1990,
              "authors": [{"surname": "Nobody"}], "doi": None}]
        )
        result = json.loads(web.match_reading("An essay about something else", candidates))
        assert result["id"] is None
        assert result["method"] == "below threshold"


class TestHeaderGatedGrids:
    """one-line-per-row grids have no ruled lines the runs path can see, so
    they are admitted only when a header row names a time column and a content
    column. a hanging-indent citation list must never pass that gate."""

    def _payload(self, page_lines):
        runs = []
        for y, cells in page_lines:
            for x, text in cells:
                runs.append({"text": text, "x": x, "y": y, "w": 8.0 * len(text), "h": 11, "size": 11})
        return {"pages": [{"number": 1, "width": 612, "height": 792, "runs": runs}],
                "filename": "t.pdf", "sha256": "t"}

    def test_single_line_grid_with_header_is_found(self):
        rows = [(72, [(72, "Week"), (150, "Date"), (280, "Topic"), (430, "Readings")])]
        for i in range(1, 9):
            y = 72 + i * 16
            rows.append((y, [(72, str(i)), (150, f"1/{i + 6}"), (280, "A Topic"), (430, "Chapter " + str(i))]))
        doc = document_from_runs(self._payload(rows))
        assert doc.pages[0].tables, "header-gated grid was not reconstructed"
        grid = doc.pages[0].tables[0]
        assert len(grid) >= 8

    def test_hanging_indent_citations_are_not_a_table(self):
        rows = []
        for i in range(12):
            y = 72 + i * 26
            rows.append((y, [(72, f"Surname{i}, Given. 2020. \"A Title That Wraps\"")]))
            rows.append((y + 13, [(108, "Journal of Examples 1(2): 10-20.")]))
        doc = document_from_runs(self._payload(rows))
        assert doc.pages[0].tables == []


class TestColumnGaps:
    """pdf.js reports a column gap as a whitespace run many times wider than a
    space, not as a positional gap. the parity fixtures cannot catch this,
    because they are built from pymupdf spans which already expand it, so it is
    pinned directly."""

    def _line(self, runs):
        from vault.text.runs import Line, Run

        return Line([Run(*r) for r in runs]).text

    def test_a_wide_whitespace_run_becomes_a_column_gap(self):
        # text, x, y, w, h, size
        text = self._line([
            ("Weekly Assessments", 78, 100, 101, 12, 12),
            (" ", 179, 100, 58, 12, 12),
            ("4", 237, 100, 6, 12, 12),
            ("0%", 243, 100, 15, 12, 12),
        ])
        assert "Weekly Assessments" in text and "40%" in text
        # the weights parser reads a run of spaces as the column boundary
        from vault.syllabus.deliverables import TABLE_WEIGHT_RE

        match = TABLE_WEIGHT_RE.match(text)
        assert match, f"weights table unreadable: {text!r}"
        assert match.group("title") == "Weekly Assessments"
        assert match.group("weight") == "40"

    def test_an_ordinary_space_run_stays_one_space(self):
        text = self._line([
            ("Introduction", 72, 100, 60, 12, 12),
            (" ", 132, 100, 3, 12, 12),
            ("to", 135, 100, 10, 12, 12),
        ])
        assert text == "Introduction to"
