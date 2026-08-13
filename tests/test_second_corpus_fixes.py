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
        c = parse_citation("Lindqvist (15) and Osei (14) in Comparative Politics.")
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
            "Halvorsen, Ida B. December 2022. Defense Primer: Planning, "
            "Programming, Budgeting, and Execution (PPBE) Process. "
            "Congressional Research Service"
        )
        assert c.matched_pattern == "dated_unquoted_report"
        assert c.year == 2022
        assert "Congressional Research Service" in (c.container or "")

    def test_cfr_name_first(self):
        c = parse_citation(
            "The Sample Control List eCFR :: 15 CFR Part 999 -- The Sample Control List"
        )
        assert c.matched_pattern == "cfr_citation"
        assert c.report_number == "15 CFR Part 999"

    def test_cfr_name_after(self):
        c = parse_citation("eCFR :: 22 CFR Part 888 -- The Sample Sample Munitions List")
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
            "Halvorsen, Ida A. and Tomas Berg (eds.), Comparative Politics Today. "
            "New York, etc: Longman, 2010, 4th edition, chapter 1."
        )
        assert c.matched_pattern == "book_year_last"
        assert c.year == 2010

    def test_two_cities_semicolon(self):
        c = parse_citation(
            "Halvorsen, Ida. Patterns of Governance: Forms and Performance "
            "in Thirty Countries. New Haven; London: Yale University Press, 2012, "
            "second edition, chapters 1-3."
        )
        assert c.matched_pattern == "book_year_last"

    def test_single_city_unchanged(self):
        c = parse_citation(
            "Halvorsen, Ida. The Northern Union: A Very Short Introduction. "
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


class TestWeightRowsTheBrowserSees:
    """the two extraction paths hand the same table over differently.

    the command line has pdfplumber and keeps a grading table's columns as runs
    of spaces; the browser has positioned text runs and often collapses the
    same gap to one space, or keeps the section heading on the first row. the
    weights were read from the spacing, so the same syllabus totalled 100 on
    one path and 0 or 50 on the other. the website runs the second one.
    """

    def test_heading_sharing_the_first_row(self):
        from vault.syllabus.deliverables import (INLINE_SECTION_LABEL_RE,
                                                 TABLE_WEIGHT_RE)
        raw = "Grading Scheme:      Attendance            40%"
        label = INLINE_SECTION_LABEL_RE.match(raw)
        assert label
        m = TABLE_WEIGHT_RE.match(raw[label.end():])
        assert m and m.group("title") == "Attendance" and m.group("weight") == "40"

    def test_a_title_ending_in_a_colon_is_not_a_heading(self):
        """"Essay 1: 20%" names the assignment; nothing may be stripped."""
        from vault.syllabus.deliverables import INLINE_SECTION_LABEL_RE
        assert not INLINE_SECTION_LABEL_RE.match("Essay 1: 20%")

    def test_single_space_row(self):
        from vault.syllabus.deliverables import LINE_WEIGHT_RE
        for raw, title, weight in (
            ("Quizzes 30%", "Quizzes", "30"),
            ("Assignments 40%", "Assignments", "40"),
            ("Exam 1 15%", "Exam 1", "15"),
            ("Late within one day 20%", "Late within one day", "20"),
        ):
            m = LINE_WEIGHT_RE.match(raw)
            assert m, raw
            assert m.group("title") == title and m.group("weight") == weight

    def test_prose_ending_in_a_percentage_is_not_a_row(self):
        from vault.syllabus.deliverables import LINE_WEIGHT_RE
        for raw in (
            "The final exam for this course is worth 30%",
            "A late submission without a valid excuse is docked 20%",
        ):
            assert not LINE_WEIGHT_RE.match(raw), raw

    def test_a_grade_scale_row_is_not_a_weights_row(self):
        from vault.syllabus.deliverables import LINE_WEIGHT_RE
        assert not LINE_WEIGHT_RE.match("94 – 100% A 76 – 79.99% C+")


class TestTheShareWrittenBeforeTheName:
    """a grading list is often written share first, and none of the patterns
    above expect that, so those courses had no weights read at all.

    the catch is that a grading scale is written share first too. "94% or
    greater" is a boundary, not a piece of work, and counting it as one took
    one course's graded total to 160.
    """

    def test_a_share_first_row_is_read(self):
        from vault.syllabus.deliverables import LEADING_WEIGHT_RE
        for raw, title, weight in (
            ("65% - Practice Sets", "Practice Sets", "65"),
            ("  25% - Group and Individual Work", "Group and Individual Work", "25"),
            ("- 30% participation", "participation", "30"),
            ("10%: Timeline assignment", "Timeline assignment", "10"),
        ):
            m = LEADING_WEIGHT_RE.match(raw)
            assert m, raw
            assert m.group("title").strip() == title and m.group("weight") == weight

    def test_a_grade_boundary_is_not_an_assignment(self):
        from vault.syllabus.deliverables import LEADING_WEIGHT_RE
        for raw in (
            "94% or greater",
            "60% and below",
            "70% to 79%",
            "80% is a B",
        ):
            assert not LEADING_WEIGHT_RE.match(raw), raw

    def test_a_bare_letter_is_not_an_assignment(self):
        """the name has to be two characters, so a scale row cannot pass."""
        from vault.syllabus.deliverables import LEADING_WEIGHT_RE
        assert not LEADING_WEIGHT_RE.match("90% - A")


class TestDistinctAssignmentsStayApart:
    def test_two_titles_whose_only_shared_word_survives_the_stop_list(self):
        """"Policy Memos" and "Policy Report", both worth 30, are two things."""
        from vault.syllabus.deliverables import Deliverable, _same_assignment
        a = Deliverable(title="Policy Memos", weight_percent=30.0)
        b = Deliverable(title="Policy Report", weight_percent=30.0)
        assert not _same_assignment(a, b)

    def test_the_same_assignment_written_twice_still_merges(self):
        from vault.syllabus.deliverables import Deliverable, _same_assignment
        a = Deliverable(title="Policy Memos", weight_percent=30.0)
        b = Deliverable(title="Weekly Policy Memos", weight_percent=30.0)
        assert _same_assignment(a, b)

    def test_a_midterm_and_a_final_are_not_one_exam(self):
        from vault.syllabus.deliverables import Deliverable, _same_assignment
        a = Deliverable(title="Midterm Exam", weight_percent=30.0)
        b = Deliverable(title="Final Exam", weight_percent=30.0)
        assert not _same_assignment(a, b)


class TestExtraCreditSitsOnTop:
    def test_bonus_is_not_counted_into_the_hundred(self):
        from vault.syllabus.deliverables import Deliverable, DeliverableSet, _check_weights
        result = DeliverableSet(items=[
            Deliverable(title="Weekly Assessments", weight_percent=40.0),
            Deliverable(title="Exams (3)", weight_percent=40.0),
            Deliverable(title="Activities", weight_percent=20.0),
            Deliverable(title="optional extra credit assignment", weight_percent=3.0),
        ])
        _check_weights(result)
        assert result.weight_total == 100.0
        assert result.weight_warning is None

    def test_the_bonus_keeps_its_own_weight(self):
        from vault.syllabus.deliverables import Deliverable, DeliverableSet, _check_weights
        bonus = Deliverable(title="Bonus quiz", weight_percent=5.0)
        result = DeliverableSet(items=[
            Deliverable(title="Final paper", weight_percent=100.0), bonus])
        _check_weights(result)
        assert result.weight_total == 100.0
        assert bonus.weight_percent == 5.0


class TestStarredAssignmentRows:
    """a recurring assignment printed among the readings.

    a seminar that rotates presentations between groups prints the rotation
    inside the schedule, once per week it comes round. four of those rows were
    being collected as readings. the word naming the work has to close the
    line, or a citation that merely mentions a report goes with them.
    """

    def test_group_rotation_row(self):
        for text in (
            "*Team 1 & 2:  Weekly Field Report & Presentation",
            "*Team Resource Presentations",
            "*Assign Teams and Agency Briefs",
            "*Policy Memo & Task Templates",
        ):
            assert schedule.DELIVERABLE_HINT_RE.match(text), text

    def test_a_citation_naming_a_report_is_left_alone(self):
        for text in (
            "*Smith, John. 2020. A Report on Trade Policy. Foreign Affairs.",
            "Berg, Tomas. March 2023. Export Controls, CRS Report.",
        ):
            assert not schedule.DELIVERABLE_HINT_RE.match(text), text

    def test_the_star_is_required(self):
        """without it the rule would reach any line ending in a work word."""
        assert not schedule.DELIVERABLE_HINT_RE.match("Group Critical Mineral Presentations")


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
                      "Late within one day", "Late after four days", "2 days late",
                      "Grading Policies", "Grading Scale", "Grading summary"):
            assert _APPARATUS_RE.match(title), title

    def test_real_assignments_survive(self):
        from vault.syllabus.deliverables import _APPARATUS_RE

        for title in ("Quizzes", "Assignments", "Exam 1", "Late Antiquity Essay",
                      "Latin America Memo"):
            assert not _APPARATUS_RE.match(title), title


class TestScheduleZoneStart:
    """which signal is allowed to say where the schedule begins.

    a deadline calendar printed above the schedule is a column of date-led
    lines. when a single such line could start the zone, that block captured
    it and every entry inside became a session: one real syllabus parsed to
    34 sessions in the browser against 27 on the command line, with four
    phantom duplicate-date warnings. the two extractors split lines slightly
    differently, so only one of them tripped it, which is what made the bug
    look like a browser problem rather than a precedence problem.
    """

    def _lines(self, *texts):
        from vault.syllabus import zones
        return [zones.Line(1, i, t, starts_block=True) for i, t in enumerate(texts)]

    def test_heading_wins_over_a_dated_deadline_block(self):
        from vault.syllabus import zones
        lines = self._lines(
            "Assignments and deadlines",
            "February, 5  NO CLASS",
            "February, 19  Deadline Essay Outline",
            "February, 26  MIDTERM EXAM",
            # as the source prints it: a heading has to look like one, and
            # sentence case fails the title-case test on its own
            "THEMATIC OUTLINE",
            "1. Introduction (01/13)",
            "2. Europe Today (01/15)",
        )
        start = zones.find_schedule_start(lines)
        assert lines[start].text == "THEMATIC OUTLINE"

    def test_dates_still_start_a_schedule_that_has_no_heading(self):
        from vault.syllabus import zones
        lines = self._lines(
            "Some front matter about the course",
            "January 13: Introduction",
            "January 15: Europe Today",
            "January 20: European Integration",
        )
        start = zones.find_schedule_start(lines)
        assert start is not None
        assert "January 13" in lines[start].text

    def test_a_heading_over_prose_does_not_take_the_zone(self):
        """"Topical Outline" heads a course description as often as a calendar.

        trusting the first schedule-ish heading put the zone on a paragraph and
        left the real table, pages later, outside it. the whole schedule was
        reported missing. the distance is the signal: several pages of policy
        prose sit between the blurb and the calendar.
        """
        from vault.syllabus import zones
        lines = self._lines(
            "Topical Outline",
            "This course provides an overview of cost concepts, enterprise",
            "budgets, financial statements, investment analysis, and other topics.",
            "Academic Honesty",
            *[f"Students are expected to adhere to this policy at all times. {n}"
              for n in range(70)],
            "8/17 - 8/19  Introduction",
            "8/24 - 8/26  Budgeting",
            "8/31 - 9/02  Accounting and Finance",
        )
        start = zones.find_schedule_start(lines)
        assert "8/17" in lines[start].text

    def test_a_heading_over_a_real_calendar_is_kept(self):
        from vault.syllabus import zones
        lines = self._lines(
            "Course Outline",
            "All readings are required unless otherwise noted.",
            "01-07  Orientation",
            "01-09  Syllabus",
            "01-14  Disaster management and sustainability",
        )
        start = zones.find_schedule_start(lines)
        assert lines[start].text == "Course Outline"

    def test_hyphen_dates_count_as_dates(self):
        """a table printing january the seventh as 01-07 still reads as dated."""
        from vault.syllabus import zones
        assert zones._DATE_ANYWHERE.search("01-07")
        assert zones._DATE_ANYWHERE.search("Week 2 01/14 Topic")
        # a month over twelve is not a date
        assert not zones._DATE_ANYWHERE.search("CAPS 24/7 crisis support")
        assert not zones._DATE_ANYWHERE.search("call 706-542-8479")

    def test_week_markers_still_outrank_everything(self):
        from vault.syllabus import zones
        lines = self._lines(
            "Course schedule",
            "Week 1: Introduction",
            "Week 2: Europe Today",
        )
        start = zones.find_schedule_start(lines)
        # the heading just above the first week is pulled in, not skipped
        assert lines[start].text in ("Course schedule", "Week 1: Introduction")


class TestTermIsNotAPublicationDate:
    """a season and year appear in every other bibliography entry.

    scanning the whole document for a term meant a reading published in
    "Spring/Summer 2016" set the course term, so a syllabus taught in 2026
    reported itself as ten years old and dated every session to match.
    """

    def test_a_compound_season_is_a_journal_issue(self):
        from vault.syllabus.dates import find_term
        assert find_term("Spring/Summer 2016; 01 - Drafting") is None
        assert find_term("Winter/Spring 2019; 02") is None

    def test_a_real_term_still_reads(self):
        from vault.syllabus.dates import find_term
        assert str(find_term("Course syllabus, Fall 2026")) == "Fall 2026"
        assert str(find_term("2026 Spring")) == "Spring 2026"


class TestBulletedRunsSplit:
    """one line carrying a whole week's readings between bullets."""

    def test_three_readings_on_one_line(self):
        from vault.syllabus.schedule import _split_bulleted_run
        assert _split_bulleted_run(
            "• RLMO, Ch. 2 • Seawright & Gerring (2008) • Mahoney (2012)"
        ) == ["RLMO, Ch. 2", "Seawright & Gerring (2008)", "Mahoney (2012)"]

    def test_a_single_bulleted_reading_is_left_whole(self):
        from vault.syllabus.schedule import _split_bulleted_run
        assert _split_bulleted_run("• RLMO, Ch. 15") == []

    def test_a_hyphen_does_not_split_a_title(self):
        from vault.syllabus.schedule import _split_bulleted_run
        assert _split_bulleted_run("Smith - A Study of War - Chapter 2") == []


class TestReadingListLabels:
    def test_the_label_on_a_list_is_not_a_reading(self):
        from vault.syllabus.schedule import _LEVEL_WORDS_ROW
        for text in ("Required Reading:", "Suggested Readings", "Optional Materials",
                     "Further Reading:", "Required"):
            assert _LEVEL_WORDS_ROW.match(text), text

    def test_a_title_that_starts_with_one_survives(self):
        from vault.syllabus.schedule import _LEVEL_WORDS_ROW
        for text in ("Reading the Landscape", "Required reading is heavy this week"):
            assert not _LEVEL_WORDS_ROW.match(text), text

    def test_a_heading_glued_to_the_last_entry_is_stripped(self):
        from vault.syllabus.schedule import _TRAILING_LEVEL_LABEL_RE
        assert _TRAILING_LEVEL_LABEL_RE.sub(
            "", "Text of the CWC: Chemical Weapons Convention Suggested Reading:"
        ).strip() == "Text of the CWC: Chemical Weapons Convention"


class TestShortFormCitations:
    """the form a seminar list is written in, with the full entry elsewhere."""

    def test_author_year_pairs(self):
        for text in ("Seawright & Gerring (2008)", "Powers and Renshon (2023)",
                     "Gibler, Miller, & Little (2016)", "Kertzer (2022)",
                     "Schenoni et al. (2023), including Appendix B"):
            assert parse_citation(text).matched_pattern == "author_year_short", text

    def test_a_chapter_tail_is_kept(self):
        c = parse_citation("Goertz (2020), Ch. 2-3")
        assert c.matched_pattern == "author_year_short"
        assert "2-3" in (c.pages or "")

    def test_prose_citing_a_year_is_not_a_reading(self):
        for text in ("The recent study (2020) showed that trade barriers fell",
                     "see the appendix (2020)"):
            assert parse_citation(text).matched_pattern != "author_year_short", text

    def test_a_named_book_with_its_chapter(self):
        assert parse_citation("Book: Hazard Analysis; Chapter 1").matched_pattern == "named_book_chapter"
        assert parse_citation("Book: Hazard Analysis: Chapter 2").matched_pattern == "named_book_chapter"

    def test_a_page_title_carrying_its_site(self):
        c = parse_citation("Country Profiles | The Arms Data Project")
        assert c.matched_pattern == "page_title_with_site"
        assert c.container == "The Arms Data Project"


class TestStatedTotals:
    def test_each_and_total_takes_the_total(self):
        from vault.syllabus.deliverables import TOTAL_WEIGHT_RE
        m = TOTAL_WEIGHT_RE.search("2. Exams (15% each; 30% total).")
        assert m and m.group("weight") == "30"

    def test_a_bare_total_is_read(self):
        from vault.syllabus.deliverables import TOTAL_WEIGHT_RE
        m = TOTAL_WEIGHT_RE.search("Diplomacy Lab (40% total, as divided below)")
        assert m and m.group("weight") == "40"

    def test_a_declared_total_absorbs_its_parts(self):
        from vault.syllabus.deliverables import Deliverable, _Candidate, _absorb_subdivisions
        parent = _Candidate(Deliverable(title="Diplomacy Lab", weight_percent=40.0),
                            "", declares_total=True)
        parts = [_Candidate(Deliverable(title=name, weight_percent=10.0), "")
                 for name in ("Literature Review", "Country Report", "Research Tasks", "Reflection")]
        kept = _absorb_subdivisions([parent] + parts)
        assert [c.item.title for c in kept] == ["Diplomacy Lab"]

    def test_ordinary_assignments_are_never_absorbed(self):
        """three that happen to add up to a fourth must all survive."""
        from vault.syllabus.deliverables import Deliverable, _Candidate, _absorb_subdivisions
        items = [
            _Candidate(Deliverable(title="Final essay", weight_percent=40.0), ""),
            _Candidate(Deliverable(title="Quiz 1", weight_percent=10.0), ""),
            _Candidate(Deliverable(title="Quiz 2", weight_percent=10.0), ""),
            _Candidate(Deliverable(title="Midterm", weight_percent=20.0), ""),
        ]
        assert len(_absorb_subdivisions(items)) == 4


class TestHeaderFieldsRunTogether:
    """a two column header block arrives as one joined line in the browser.

    "Instructor: Dana Okafor Time: Tues 2:00-4:45" gave the instructor a name
    with the meeting time inside it and left the time unfound. the command
    line splits the same header differently and never saw it.
    """

    def test_a_value_stops_at_the_next_label(self):
        from vault.syllabus.frontmatter import _value_up_to_next_label
        assert _value_up_to_next_label(
            "Dana Okafor Time: Tues 2:00-4:45", "instructor") == "Dana Okafor"
        assert _value_up_to_next_label(
            "Dana Okafor Office Hours: by appointment", "instructor") == "Dana Okafor"

    def test_a_plain_value_is_untouched(self):
        from vault.syllabus.frontmatter import _value_up_to_next_label
        assert _value_up_to_next_label("Rowan Ashe", "instructor") == "Rowan Ashe"


class TestInstructorLooksLikeAPerson:
    """the record header prints this, so a wrong answer is now visible."""

    def test_real_names_survive(self):
        from vault.syllabus.frontmatter import _plausible_name
        for name in ("Rowan Ashe", "Dr. Priya Raman", "Alex Whitfield (she/her)",
                     "Dana Okafor, Ph.D., Assistant Professor"):
            assert _plausible_name(name) == name.strip(), name

    def test_prose_that_matched_the_label_is_dropped(self):
        from vault.syllabus.frontmatter import _plausible_name
        for junk in ("may be necessary.", "_____________________________",
                     "• Will antibiotics work 50 years from now?",
                     ". Failure to follow the academic honesty policy will have serious consequences.",
                     "Information", "Drop-in hours"):
            assert _plausible_name(junk) is None, junk

    def test_empty_brackets_from_a_stripped_email_go(self):
        from vault.syllabus.frontmatter import _plausible_name
        assert _plausible_name("Dr. Priya Raman ()") == "Dr. Priya Raman"
