"""the three schedule structures, parsed end to end against expected json.

exact counts are the backbone here. a parser that returns four readings for a
week that has five looks identical to a correct one from the outside, and a
count assertion is what tells them apart.
"""

import json
import os
from pathlib import Path

import pytest

from vault.syllabus.pipeline import parse_syllabus

FIXTURES = Path(__file__).parent / "fixtures" / "syllabi"
EXPECTED = Path(__file__).parent / "expected"

NAMES = ["structure-a-bulleted", "structure-b-table", "structure-c-labelled"]


def load(name: str):
    parsed = parse_syllabus(FIXTURES / f"{name}.pdf")
    expected = json.loads((EXPECTED / f"{name}.json").read_text(encoding="utf-8"))
    return parsed, expected


@pytest.fixture(scope="module", params=NAMES)
def case(request):
    return load(request.param)


class TestStructure:
    def test_structure_detected(self, case):
        parsed, expected = case
        assert parsed.structure == expected["structure"]

    def test_course_metadata(self, case):
        parsed, expected = case
        want = expected["course"]
        assert parsed.course.code == want["code"]
        assert parsed.course.title == want["title"]
        assert parsed.course.term.name == want["term"]
        assert parsed.course.term.year == want["year"]
        assert parsed.course.instructor_name == want["instructor_name"]

    def test_ai_stance(self, case):
        parsed, expected = case
        assert parsed.ai_stance == expected["ai_stance"]

    def test_session_count_exact(self, case):
        parsed, expected = case
        assert len(parsed.sessions) == expected["session_count"]

    def test_reading_counts_exact(self, case):
        parsed, expected = case
        for week, want in expected["reading_counts"].items():
            got = sum(
                len(s.readings) for s in parsed.sessions if s.week_number == int(week)
            )
            assert got == want, f"week {week}: expected {want} readings, parsed {got}"

    def test_weight_total(self, case):
        parsed, expected = case
        assert parsed.deliverables.weight_total == expected["weight_total"]

    def test_expected_citations(self, case):
        parsed, expected = case
        for week, wants in expected.get("citations", {}).items():
            readings = [
                r for s in parsed.sessions if s.week_number == int(week) for r in s.readings
            ]
            assert len(readings) == len(wants)
            for reading, want in zip(readings, wants):
                citation = reading.citation
                if "authors" in want:
                    surnames = [a.surname or a.literal for a in citation.authors]
                    for surname in want["authors"]:
                        assert surname in surnames, (
                            f"week {week}: wanted author {surname!r} in {surnames}"
                        )
                if "title" in want:
                    assert citation.title == want["title"]
                if "container" in want:
                    assert citation.container == want["container"]
                if "year" in want:
                    assert citation.year == want["year"]
                if "pages" in want:
                    assert citation.pages == want["pages"]
                if "report_number" in want:
                    assert citation.report_number == want["report_number"]
                if "work_type" in want:
                    assert citation.work_type == want["work_type"]
                if "pages_only" in want:
                    assert want["pages_only"] in (citation.pages or reading.page_range or "")


class TestStructureSpecifics:
    def test_no_reading_weeks_are_not_given_readings(self):
        parsed, expected = load("structure-a-bulleted")
        for week, kind in expected["session_types"].items():
            sessions = [s for s in parsed.sessions if s.week_number == int(week)]
            assert sessions and sessions[0].session_type == kind
            assert sessions[0].readings == []

    def test_twice_weekly_sessions_split(self):
        parsed, expected = load("structure-b-table")
        for week, labels in expected["sub_sessions"].items():
            got = [
                s.sub_session_label
                for s in parsed.sessions
                if s.week_number == int(week) and s.sub_session_label
            ]
            assert got == labels

    def test_content_warning_captured(self):
        parsed, expected = load("structure-b-table")
        week = expected["content_warning_week"]
        warnings = [
            r.content_warning
            for s in parsed.sessions
            if s.week_number == week
            for r in s.readings
            if r.content_warning
        ]
        assert warnings, "the content warning bullet was lost"
        assert "violence" in warnings[0]

    def test_exam_session_has_no_invented_reading(self):
        parsed, expected = load("structure-b-table")
        for week in expected["exam_weeks"]:
            exams = [
                s for s in parsed.sessions
                if s.week_number == week and s.session_type == "exam"
            ]
            assert exams
            assert all(s.readings == [] for s in exams)

    def test_holiday_recorded_not_fabricated(self):
        parsed, expected = load("structure-c-labelled")
        holidays = [s for s in parsed.sessions if s.session_type == "holiday"]
        assert [s.meeting_date.isoformat() for s in holidays] == expected["holiday_dates"]
        assert all(s.readings == [] for s in holidays)

    def test_important_dates_block(self):
        parsed, expected = load("structure-c-labelled")
        want = expected["important_dates"]
        assert len(parsed.important_dates) == want["count"]
        spring_break = next(
            d for d in parsed.important_dates if "break" in d.label.lower()
        )
        assert spring_break.start.isoformat() == want["spring_break_start"]
        assert spring_break.end.isoformat() == want["spring_break_end"]

    def test_requirement_levels_preserved(self):
        parsed, expected = load("structure-c-labelled")
        for week, levels in expected["requirement_levels"].items():
            got = [
                r.requirement_level
                for s in parsed.sessions
                if s.week_number == int(week)
                for r in s.readings
            ]
            assert got == levels


class TestNoKeysNeeded:
    def test_pipeline_runs_with_no_api_keys_in_the_environment(self, monkeypatch):
        for name in list(os.environ):
            if "KEY" in name or "TOKEN" in name or name.startswith("VAULT_LLM"):
                monkeypatch.delenv(name, raising=False)
        parsed = parse_syllabus(FIXTURES / "structure-a-bulleted.pdf")
        assert len(parsed.sessions) == 5
        assert parsed.reading_count == 8

    def test_no_model_sdk_imported_outside_the_adapter(self):
        import sys

        forbidden = {"anthropic", "openai", "google.generativeai"}
        loaded = forbidden & set(sys.modules)
        assert not loaded, f"model sdk imported by the pipeline: {loaded}"
