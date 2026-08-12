"""fixes from the second batch of real syllabi, each pinned by the exact
shape that failed. every case here is a quote or a close paraphrase of a line
from a file that parsed wrongly; none is invented.
"""

from __future__ import annotations

from vault.syllabus import schedule, zones
from vault.syllabus.citations import parse_citation
from vault.syllabus.dates import Term
from vault.syllabus.frontmatter import _FILENAME_TERM_RE


class TestSetTextShorthand:
    def test_acronym_chapter_without_comma(self):
        c = parse_citation("NRC Ch 1")
        assert c.matched_pattern == "author_short_chapter"
        assert c.authors[0].literal or c.authors[0].surname

    def test_ampersand_chapter_pair(self):
        assert parse_citation("NRC Ch 3 & 4").matched_pattern == "author_short_chapter"

    def test_the_comma_form_still_works(self):
        assert parse_citation("Okonkwo and Osei, Chapter 1").matched_pattern == "author_short_chapter"


class TestChapterInContainer:
    def test_surname_with_chapter_number(self):
        c = parse_citation("Okonkwo (12) in Comparative Politics.")
        assert c.matched_pattern == "chapter_in_container"
        assert c.authors[0].surname == "Okonkwo"
        assert c.pages == "chapter 12"
        assert c.container == "Comparative Politics"

    def test_two_authors_two_chapters(self):
        c = parse_citation("Lindqvist (15) and Peters (14) in Comparative Politics.")
        assert c.pages == "chapters 15, 14"
        assert len(c.authors) == 2

    def test_bare_surname(self):
        assert parse_citation("Berg in Comparative Politics.").matched_pattern == "chapter_in_container"

    def test_editor_shorthand_container(self):
        c = parse_citation("Hine in Hale & Osei")
        assert c.matched_pattern == "chapter_in_container"
        assert c.container == "Hale & Osei"

    def test_lowercase_container_does_not_match(self):
        """'discussed in class' must not become a citation."""
        assert parse_citation("Discussed in class").matched_pattern is None


class TestDatedReports:
    def test_month_year_unquoted_report(self):
        c = parse_citation(
            "Halvorsen, Brendan W. December 2022. Defense Primer: Planning, "
            "Programming, Budgeting, and Execution (PPBE) Process. "
            "Congressional Research Service"
        )
        assert c.matched_pattern == "dated_unquoted_report"
        assert c.year == 2022
        assert "Congressional Research Service" in (c.container or "")

    def test_cfr_name_first(self):
        c = parse_citation(
            "The Sample Control List eCFR :: 15 CFR Part 774 -- The Sample Control List"
        )
        assert c.matched_pattern == "cfr_citation"
        assert c.report_number == "15 CFR Part 774"

    def test_cfr_name_after(self):
        c = parse_citation("eCFR :: 22 CFR Part 121 -- The Sample Sample Munitions List")
        assert c.matched_pattern == "cfr_citation"
        assert c.title == "The Sample Sample Munitions List"


class TestFusedReadingColumns:
    def test_required_and_suggested_split(self):
        out = schedule._split_fused_columns(["NRC Ch 3 & 4 Greenfire Movie"])
        assert out == [("NRC Ch 3 & 4", None), ("Greenfire Movie", "recommended")]

    def test_level_word_subheader_is_dropped_everywhere(self):
        assert schedule._build_reading("Required Suggested", 0) is None

    def test_terse_chapter_cite_is_not_a_fragment(self):
        assert not schedule._is_fragment("NRC Ch 3 & 4")
        assert schedule._is_fragment("mode/2up")


class TestMultiPlaceImprint:
    def test_new_york_etc(self):
        c = parse_citation(
            "Halvorsen, Gabriel A. and Kaare Strøm (eds.), Comparative Politics Today. "
            "New York, etc: Longman, 2010, 4th edition, chapter 1."
        )
        assert c.matched_pattern == "book_year_last"
        assert c.year == 2010

    def test_two_cities_semicolon(self):
        c = parse_citation(
            "Halvorsen, Arend. Patterns of Democracy: Government Forms and Performance "
            "in Thirty-Six Countries. New Haven; London: Yale University Press, 2012, "
            "second edition, chapters 1-3."
        )
        assert c.matched_pattern == "book_year_last"

    def test_single_city_unchanged(self):
        c = parse_citation(
            "Halvorsen, John. The European Union: A Very Short Introduction. "
            "Oxford: Oxford University Press, 2018, chapter 3."
        )
        assert c.matched_pattern == "book_year_last"


class TestTableHeaders:
    def test_combined_week_dates_header(self):
        """'Week dates (days M-F)' names the anchor column of a real table."""
        grid = [
            ["Week dates (days M-F)", "Topic", "Reading"],
            ["August 17 - 19", "Course Introduction", "NRC Ch 1"],
        ]
        shape = schedule._shape_from_header(grid)
        assert shape.from_header
        assert shape.week_col == 0
        assert shape.date_cols == [0]

    def test_split_header_row_is_merged(self):
        """a 'Topic' label on the row under the header names its column."""
        grid = [
            ["Class\n#", "Date", "", "Due Dates (@11:59PM EST)"],
            ["", "", "Topic", ""],
            ["1", "1/8", "Orientation", "Welcome Survey"],
        ]
        shape = schedule._shape_from_header(grid)
        assert shape.topic_col == 2
        # with every column named, nothing is swept into the readings
        _, topic, _, body = schedule._row_cells(grid[2], shape)
        assert topic == "Orientation"
        assert body == ""

    def test_tall_header_cell_read_whole(self):
        """'Exams and\\nTeam\\nAssignments due' is a due column."""
        grid = [
            ["Week", "Date", "Assigned reading", "Exams and\nTeam\nAssignments due"],
            ["1", "Aug\n20", "RLMO, C1", "—"],
        ]
        shape = schedule._shape_from_header(grid)
        assert shape.body_cols == [2]
        assert shape.due_cols == [3]

    def test_a_data_row_is_not_a_header_continuation(self):
        grid = [
            ["Week", "Date", ""],
            ["1", "1/8", "Notes about week one"],
        ]
        shape = schedule._shape_from_header(grid)
        # 'Notes about week one' has no digits but is not a lone label row
        assert shape.topic_col is None


class TestNumericDateUnderBareWeek:
    def test_labelled_week_takes_its_body_date(self):
        lines = [
            zones.Line(1, 0, "Week 1", starts_block=True),
            zones.Line(1, 1, "T", starts_block=False),
            zones.Line(1, 2, "8/18 Important Course Information", starts_block=False),
        ]
        parsed = schedule._parse_labelled(lines, Term("fall", 2026))
        assert len(parsed.sessions) == 1
        d = parsed.sessions[0].meeting_date
        assert d is not None and (d.month, d.day) == (8, 18)

    def test_a_second_date_does_not_restamp(self):
        lines = [
            zones.Line(1, 0, "Week 1", starts_block=True),
            zones.Line(1, 1, "8/18 First meeting", starts_block=False),
            zones.Line(1, 2, "8/20 Second meeting", starts_block=False),
        ]
        parsed = schedule._parse_labelled(lines, Term("fall", 2026))
        d = parsed.sessions[0].meeting_date
        assert (d.month, d.day) == (8, 18)


class TestZoneRepairs:
    def test_month_led_heading_without_punctuation(self):
        """'Jan 13  Introduction' is a schedule line without the colon."""
        assert zones._MONTH_LED.match("Jan 13  Introduction")
        assert zones._MONTH_LED.match("Mar 3 “The Victorian Age” (E 3)")
        assert not zones._MONTH_LED.match("jan 13 we will discuss the reading")

    def test_filename_term(self):
        m = _FILENAME_TERM_RE.search("HIST1234_Ashe_Spring2026_Syllabus.pdf")
        assert m and m.group(1).lower() == "spring" and m.group(2) == "2026"

    def test_notable_dates_heading_is_read(self):
        import re as _re
        pattern = r"^\s*(?:important|notable|key)\s+dates\s*:?\s*$"
        for heading in ("Important dates:", "Notable dates:", "Key Dates"):
            assert _re.match(pattern, heading, _re.IGNORECASE), heading


class TestGradingApparatus:
    def test_total_and_late_scale_are_not_assignments(self):
        from vault.syllabus.deliverables import _APPARATUS_RE

        for title in ("TOTAL", "Total", "On-time", "On time",
                      "Late within one day", "Late after four days", "2 days late"):
            assert _APPARATUS_RE.match(title), title

    def test_real_assignments_survive(self):
        from vault.syllabus.deliverables import _APPARATUS_RE

        for title in ("Quizzes", "Assignments", "Exam 1", "Late Antiquity Essay",
                      "Latin America Memo"):
            assert not _APPARATUS_RE.match(title), title
