"""header-driven table reading.

real schedule tables run past three columns and name their weeks in ways the
positional reader guessed wrong: a bare integer under a "Week" heading, dates
written "01-07", a "Meetings" column carrying both. these tests pin the shape
detection and the anchor rules with synthetic grids, so no real course content
is involved.
"""

from pathlib import Path

from vault.syllabus import schedule
from vault.syllabus.dates import Term
from vault.text.model import ExtractedDoc, ExtractedPage
from vault.syllabus import zones


def doc_with_grid(grid, page_text="Week"):
    page = ExtractedPage(
        number=1,
        text=page_text,
        raw_text=page_text,
        tables=[grid],
        block_texts=[page_text],
    )
    return ExtractedDoc(path=Path("t.pdf"), file_hash="t", page_count=1, pages=[page])


def schedule_zone(doc):
    line = zones.Line(1, 0, doc.pages[0].text, starts_block=True)
    zone = zones.Zone(zones.SCHEDULE, None, [line])
    return [zone]


class TestShapeFromHeader:
    def test_six_column_header_is_mapped(self):
        grid = [
            ["Week", "Date", "Unit", "Topic", "Material Due", "Other Due"],
            ["1", "01-07", "A", "Orientation", "---", "Survey"],
        ]
        shape = schedule._shape_from_header(grid)
        assert shape.from_header
        assert shape.week_col == 0
        assert shape.date_cols == [1]
        assert shape.topic_col == 3
        assert shape.body_cols == [4, 5]

    def test_meetings_column_serves_as_week_and_date(self):
        grid = [
            ["Meetings", "Topic", "Due Dates (@11:59PM EST)"],
            ["1", "Opening", ""],
        ]
        shape = schedule._shape_from_header(grid)
        assert shape.from_header
        assert shape.week_col == 0
        assert shape.date_cols == [0]
        assert shape.body_cols == [2]

    def test_one_recognised_label_is_not_a_header(self):
        grid = [
            ["Notes", "whatever", "text"],
            ["a", "b", "c"],
        ]
        assert not schedule._shape_from_header(grid).from_header

    def test_unit_column_stands_in_for_a_missing_topic(self):
        grid = [
            ["Date", "Unit", "Readings"],
            ["1/7", "Foundations", "Chapter 1"],
        ]
        shape = schedule._shape_from_header(grid)
        assert shape.from_header
        assert shape.topic_col == 1
        assert shape.unit_col is None


class TestTableSessions:
    def test_bare_week_numbers_and_dash_dates(self):
        grid = [
            ["Week", "Date", "Topic", "Material Due"],
            ["1", "01-07", "Orientation", ""],
            ["", "01-09", "", "Syllabus quiz"],
            ["2", "01-14", "Foundations", "Reading response"],
        ]
        doc = doc_with_grid(grid)
        parsed = schedule.parse(doc, schedule_zone(doc), Term("spring", 2025))
        assert parsed.structure == schedule.TABLE
        weeks = [(s.week_number, str(s.meeting_date)) for s in parsed.sessions]
        assert weeks == [
            (1, "2025-01-07"),
            (1, "2025-01-09"),
            (2, "2025-01-14"),
        ]

    def test_dated_row_without_week_continues_the_week_above(self):
        grid = [
            ["Week", "Date", "Topic", "Readings"],
            ["3", "02-04", "First meeting", "Chapter 5"],
            ["", "02-06", "Second meeting", "Chapter 6"],
        ]
        doc = doc_with_grid(grid)
        parsed = schedule.parse(doc, schedule_zone(doc), Term("spring", 2025))
        assert [s.week_number for s in parsed.sessions] == [3, 3]

    def test_topic_column_never_reaches_the_reading_list(self):
        grid = [
            ["Week", "Date", "Topic", "Readings"],
            ["1", "01-07", "A Topic That Looks Like A Title", ""],
        ]
        doc = doc_with_grid(grid)
        parsed = schedule.parse(doc, schedule_zone(doc), Term("spring", 2025))
        assert parsed.sessions[0].topic == "A Topic That Looks Like A Title"
        assert parsed.sessions[0].readings == []

    def test_page_range_in_a_reading_cell_is_not_a_date(self):
        grid = [
            ["Week", "Date", "Topic", "Readings"],
            ["1", "01-07", "Opening", "Pages 29-33 in The Open Textbook"],
        ]
        doc = doc_with_grid(grid)
        parsed = schedule.parse(doc, schedule_zone(doc), Term("spring", 2025))
        session = parsed.sessions[0]
        assert str(session.meeting_date) == "2025-01-07"
        assert len(session.readings) == 1
        assert session.readings[0].citation.pages == "29-33"

    def test_headerless_grid_keeps_the_positional_reading(self):
        grid = [
            ["Week 1\n8/14", "Opening", "Voss, Mara. 2019. \"A Title.\" Journal 1(1): 1-10."],
        ]
        doc = doc_with_grid(grid)
        parsed = schedule.parse(doc, schedule_zone(doc), Term("fall", 2025))
        assert parsed.sessions[0].week_number == 1
        assert len(parsed.sessions[0].readings) == 1

    def test_shape_is_learned_per_grid_not_per_document(self):
        wide = [
            ["Week", "Date", "Topic", "Readings"],
            ["1", "01-07", "Opening", "Chapter 1"],
        ]
        narrow = [
            ["Week 2\n1/14", "Next", "Chapter 2"],
        ]
        page_one = ExtractedPage(
            number=1, text="Week", raw_text="Week", tables=[wide], block_texts=["Week"]
        )
        page_two = ExtractedPage(
            number=2, text="x", raw_text="x", tables=[narrow], block_texts=["x"]
        )
        doc = ExtractedDoc(
            path=Path("t.pdf"), file_hash="t", page_count=2, pages=[page_one, page_two]
        )
        line_one = zones.Line(1, 0, "Week", starts_block=True)
        line_two = zones.Line(2, 1, "x", starts_block=True)
        zone = zones.Zone(zones.SCHEDULE, None, [line_one, line_two])
        parsed = schedule.parse(doc, [zone], Term("spring", 2025))
        weeks = [s.week_number for s in parsed.sessions]
        assert weeks == [1, 2]
        assert len(parsed.sessions[1].readings) == 1


class TestParserChoice:
    """every parser runs and the best result wins. these pin the two ways the
    ranking is known to go wrong if either signal is used on its own."""

    def _doc(self, grid, text):
        page = ExtractedPage(
            number=1, text=text, raw_text=text, tables=[grid], block_texts=text.split("\n\n")
        )
        return ExtractedDoc(path=Path("t.pdf"), file_hash="t", page_count=1, pages=[page])

    def _zone(self, doc):
        lines = []
        for block in doc.pages[0].block_texts:
            for offset, raw in enumerate(block.splitlines()):
                lines.append(zones.Line(1, len(lines), raw, starts_block=offset == 0))
        return [zones.Zone(zones.SCHEDULE, None, lines)]

    def test_a_dated_table_beats_undated_shredding(self):
        # flowing text parsers run over a table find more rows than the cell
        # reader, but they are fragments and they carry no dates. counting
        # readings alone picks them, which is wrong.
        grid = [
            ["Week", "Date", "Topic", "Readings"],
            ["1", "1/7", "Opening", "Voss, Mara. 2019. \"A Real Title.\" Journal 1(1): 1-10."],
            ["2", "1/14", "Next Topic", "Ruiz, Ana. 2020. \"Another Title.\" Journal 2(2): 5-9."],
            ["3", "1/21", "Third Topic", "Weber, Sam. 2021. \"A Third Title.\" Journal 3(1): 2-8."],
        ]
        text = "Week 1 Opening\n\nWeek 2 Next Topic\n\nWeek 3 Third Topic"
        doc = self._doc(grid, text)
        parsed = schedule.parse(doc, self._zone(doc), Term("spring", 2025))
        assert parsed.structure == schedule.TABLE
        assert sum(1 for s in parsed.sessions if s.meeting_date) >= 3

    def test_a_real_reading_list_beats_a_dated_summary_grid(self):
        # the other direction: a summary grid dates every row but carries three
        # entries, while the real listing below it has the readings. ranking on
        # dates alone picks the grid.
        grid = [
            ["Date", "Class Topics", "Assignments"],
            ["Jan 7", "Opening", ""],
            ["Jan 14", "Next", ""],
            ["Jan 21", "Third", ""],
        ]
        text = (
            "Class 1: January 7 - Opening\n"
            "Voss, Mara. 2019. \"A Real Title.\" Journal of Examples 1(1): 1-10.\n"
            "Ruiz, Ana. 2020. \"Another Title.\" Journal of Examples 2(2): 5-9.\n\n"
            "Class 2: January 14 - Next\n"
            "Weber, Sam. 2021. \"A Third Title.\" Journal of Examples 3(1): 2-8.\n"
            "Nowak, Piotr. 2022. \"A Fourth Title.\" Journal of Examples 4(2): 7-9.\n\n"
            "Class 3: January 21 - Third\n"
            "Okonkwo, Adaeze. 2023. \"A Fifth Title.\" Journal of Examples 5(1): 3-6.\n"
        )
        doc = self._doc(grid, text)
        parsed = schedule.parse(doc, self._zone(doc), Term("spring", 2025))
        readings = sum(len(s.readings) for s in parsed.sessions)
        assert readings >= 5, f"took the summary grid instead of the listing ({readings} readings)"
