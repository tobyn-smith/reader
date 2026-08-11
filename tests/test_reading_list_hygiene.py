"""keeping things that are not readings out of reading lists.

this is where the accuracy actually was. measured over real syllabi, four out
of five rows that no citation pattern could read were never readings at all:
week topics, grading table columns, the week's own timetable, and urls that
wrapped onto a line of their own. every case below is one that really happened,
written out synthetically.

a reading list that carries junk is worse than one that is short. the junk gets
checked off, counted as outstanding work, and printed on a bibliography.
"""

from __future__ import annotations

from vault.syllabus import schedule
from vault.syllabus.dates import Term


def session_with(topic: str | None = None) -> schedule.SessionEntry:
    return schedule.SessionEntry(ordinal=0, page_number=1, topic=topic)


def lines(*texts: str) -> list:
    """schedule lines, first one opening a block and the rest inside it."""
    from vault.syllabus import zones

    return [
        zones.Line(1, i, text, starts_block=(i == 0))
        for i, text in enumerate(texts)
    ]


class TestNamedColumnsAreNotReadings:
    def test_a_grid_naming_only_due_columns_yields_no_readings(self):
        """a grading table has no readings in it, and should say so.

        seen on a real syllabus: week, date, unit, topic, material due, other
        due. the fallback swept every column it had not been told about into
        the reading list, so thirteen weeks of "Participation" turned up as
        things to go and read.
        """
        grid = [
            ["Week", "Date", "Unit", "Topic", "Material Due", "Other Due"],
            ["1", "01-07", "A", "Orientation", "---", "Welcome Survey"],
        ]
        shape = schedule._shape_from_header(grid)
        assert shape.body_cols == []
        assert shape.due_cols == [4, 5]

        anchor, topic, unit, body = schedule._row_cells(grid[1], shape)
        assert topic == "Orientation"
        assert body == ""

    def test_an_unnamed_column_is_still_swept_up(self):
        """guessing is right where the header genuinely said nothing."""
        grid = [
            ["Week", "Date", "Topic", ""],
            ["1", "01-07", "Orientation", "Smith 1999, Some Article"],
        ]
        shape = schedule._shape_from_header(grid)
        _, _, _, body = schedule._row_cells(grid[1], shape)
        assert "Smith 1999" in body


class TestWeeklyTimetableIsNotAReading:
    def test_a_date_led_line_inside_a_week_becomes_the_date(self):
        """a week that lists its own two meetings was listing them as readings."""
        parsed = schedule._parse_bulleted(
            lines(
                "Week 1: Introduction to the Course",
                "August 22 -What is Geography and why is it important?",
                "August 24 -What is sustainability?",
                "Reading: Chapter section 1.2",
            ),
            Term("Fall", 2023),
        )
        assert len(parsed.sessions) == 1
        session = parsed.sessions[0]
        assert session.meeting_date is not None
        assert session.meeting_date.month == 8 and session.meeting_date.day == 22
        raws = [r.citation.raw for r in session.readings]
        assert not any("What is Geography" in r for r in raws)
        assert any("Chapter section 1.2" in r for r in raws)

    def test_a_citation_carrying_a_full_date_is_still_a_reading(self):
        """the guard needs a bare month and day, so a dated report survives."""
        parsed = schedule._parse_bulleted(
            lines(
                "Week 3: Trade",
                "Lawrence, Susan V. March 3, 2021. U.S.-China Relations, IF10119.",
            ),
            Term("Spring", 2021),
        )
        raws = [r.citation.raw for r in parsed.sessions[0].readings]
        assert any("U.S.-China Relations" in r for r in raws)


class TestWrappedUrls:
    def test_a_link_only_row_joins_the_row_above(self):
        entries = [
            'Smith. "A Web Thing." In Smarthistory,',
            "https://smarthistory.org/a-web- thing/",
        ]
        assert schedule._join_url_tails(entries) == [
            'Smith. "A Web Thing." In Smarthistory, https://smarthistory.org/a-web- thing/'
        ]

    def test_a_tail_that_lost_its_scheme_joins_too(self):
        entries = [
            "Peters. The Marbles. https://theconversation.com/the-parthenon-marbles-",
            "evoke-fierce-repatriation-debates-an archaeologist- explains-why-219152",
        ]
        assert len(schedule._join_url_tails(entries)) == 1

    def test_a_page_range_after_a_citation_is_left_alone(self):
        """the tail rule must not swallow a row that merely looks path shaped."""
        entries = ["Berg. American Grand Strategy. https://example.org/x", "pp. 12-40"]
        assert len(schedule._join_url_tails(entries)) == 2

    def test_a_web_citation_keeping_its_title_stays_separate(self):
        entries = [
            "Okonkwo. Something Else.",
            'https://smarthistory.org/an-intro/ "Ilya Repin, Krestny Khod"',
        ]
        assert len(schedule._join_url_tails(entries)) == 2


class TestReadingListSubheadings:
    def test_thematic_dividers_are_recognised(self):
        for label in (
            "Human Security",
            "Energy Security",
            "Nonproliferation / Export Controls",
            "Colonial Legacies",
            "Nationalism and the Struggle for Independence",
        ):
            assert schedule._looks_like_reading_subheading(label), label

    def test_real_readings_are_not(self):
        for citation in (
            "Nye, Preface and Part I, Types of Power (pp. ix - 109)",
            'Okonkwo, Chidi. "Rationalist Accounts." International Organization 49.',
            "Berg, Introduction, pp 1-16.",
            "Hine in Hale & Osei",
            "https://example.org/a-reading",
        ):
            assert not schedule._looks_like_reading_subheading(citation), citation

    def test_a_divider_becomes_the_topic_when_the_week_has_none(self):
        session = session_with(topic=None)
        kept = schedule._lift_subheadings(session, ["Colonial Legacies", "Smith 1999, A Book"])
        assert session.topic == "Colonial Legacies"
        assert kept == ["Smith 1999, A Book"]

    def test_a_divider_is_dropped_when_the_week_already_has_a_topic(self):
        session = session_with(topic="Assessing Policy Challenges")
        kept = schedule._lift_subheadings(session, ["Human Security", "Smith 1999, A Book"])
        assert session.topic == "Assessing Policy Challenges"
        assert kept == ["Smith 1999, A Book"]


class TestWeekDescriptions:
    """the paragraph under a week heading is about the week, not to be read."""

    def test_a_description_paragraph_is_not_a_reading(self):
        for paragraph in (
            "We will discuss the intentions and outline of the course as well as our "
            "mutual expectations. We will further go over the assessment and what is "
            "expected of everyone taking part this term.",
            "Politics is essentially about power, and power is most notably exercised "
            "through the implementation of policy, which is why this week looks at how "
            "decisions actually get made and by whom in practice.",
        ):
            assert schedule._looks_like_prose(paragraph)

    def test_a_long_citation_is_not_prose(self):
        """each of these is long, and each carries one mark of a citation."""
        for citation in (
            # spelled out pages, the form that nearly got this rule reverted
            "Pages 29-37 in The Guerrilla Girls: Bedside Companion to the History of "
            "Western Art. PDF on eLC. Content warning: discussion of sexual violence",
            # a year
            "Halvorsen, Gabriel A., Russell J. Dalton and Kaare Strom, Comparative Politics "
            "Today, published in its sixth edition and covering the whole continent, 2016",
            # a quoted title
            'Berg, Kevin. "The U.S. Wants to Make Sure China Cannot Catch Up on '
            'Quantum Computing," in Foreign Policy, an essay about export controls',
            # opens with a surname, which is the one structural signal
            "Halvorsen, Arend. Patterns of Democracy: Government Forms and Performance "
            "in Thirty-Six Countries, a study of consensus and majoritarian systems",
        ):
            assert not schedule._looks_like_prose(citation), citation

    def test_a_short_line_is_never_prose(self):
        """brevity is the whole defence for short form references."""
        assert not schedule._looks_like_prose("Okonkwo (12) in Comparative Politics.")
        assert not schedule._looks_like_prose("Okonkwo and Osei, Chapters 3 and 4")


class TestGradedWorkAmongTheReadings:
    def test_a_due_line_in_a_labelled_block_is_a_deliverable(self):
        """an asterisk in front of "Due:" was hiding it from the check."""
        session = session_with()
        schedule._finish_labelled(
            session,
            [
                ("readings", "*Due: Policy Memo #1"),
                ("readings", "Okonkwo 1995, Rationalist Accounts of Bargaining Failure"),
            ],
        )
        raws = [r.citation.raw for r in session.readings]
        assert not any("Policy Memo" in r for r in raws)
        assert any("Okonkwo" in r for r in raws)
        assert any("Policy Memo" in hint for hint in session.deliverable_hints)
