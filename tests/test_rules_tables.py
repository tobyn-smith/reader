"""tables read from ruled lines, the way the browser now sends them.

each rejection case here is a shape a real syllabus produced: hyperlink
underlines minting a grid over a page of citations, a letterhead box filing
prose into three columns, a double-drawn border adding a ghost column, and a
title bar drawn inside the table box.
"""

from __future__ import annotations

from vault.text.runs import (
    Run,
    _lines_from_runs,
    _tables_from_rules,
    document_from_runs,
)


def _run(text, x, y, w=40, h=10):
    return Run(text=text, x=x, y=y, w=w, h=h, size=10)


def _lines(runs):
    return _lines_from_runs(runs)


def _mesh(xs, ys):
    """every rule of a full grid: rows spanning xs, columns spanning ys."""
    rules = []
    for y in ys:
        rules.append({"x0": xs[0], "y0": y, "x1": xs[-1], "y1": y})
    for x in xs:
        rules.append({"x0": x, "y0": ys[0], "x1": x, "y1": ys[-1]})
    return rules


class TestGridRecovery:
    def test_a_full_mesh_comes_back_as_its_cells(self):
        rules = _mesh([50, 150, 300], [100, 130, 160])
        runs = [
            _run("Week", 60, 110), _run("Topic", 160, 110),
            _run("1", 60, 140), _run("Introduction", 160, 140),
        ]
        tables = _tables_from_rules(_lines(runs), rules)
        assert len(tables) == 1
        assert tables[0] == [["Week", "Topic"], ["1", "Introduction"]]

    def test_no_rules_means_no_tables(self):
        runs = [_run("Week", 60, 110), _run("1", 60, 140)]
        assert _tables_from_rules(_lines(runs), []) == []

    def test_a_multi_line_cell_keeps_its_lines(self):
        rules = _mesh([50, 150, 300], [100, 160, 200])
        runs = [
            _run("Week", 60, 110), _run("Exams and", 160, 105),
            _run("Team", 160, 120), _run("Assignments due", 160, 135),
            _run("1", 60, 170), _run("Aug 20", 160, 170),
        ]
        tables = _tables_from_rules(_lines(runs), rules)
        assert tables[0][0][1] == "Exams and\nTeam\nAssignments due"


class TestRejections:
    def test_link_underlines_do_not_make_a_table(self):
        """underlines never cross a vertical, and a grid is a mesh."""
        rules = [
            {"x0": 60, "y0": 120, "x1": 200, "y1": 120},
            {"x0": 60, "y0": 150, "x1": 210, "y1": 150},
            {"x0": 60, "y0": 180, "x1": 190, "y1": 180},
            # a stray vertical off to the side, from a text box
            {"x0": 400, "y0": 100, "x1": 400, "y1": 200},
            {"x0": 430, "y0": 100, "x1": 430, "y1": 200},
            {"x0": 460, "y0": 100, "x1": 460, "y1": 200},
        ]
        runs = [
            _run("Trejo, Guillermo, and Sandra Ley. 2020.", 60, 108, w=140),
            _run("Yashar, Deborah. 2018.", 60, 138, w=150),
            _run("Arias, Desmond. 2017.", 60, 168, w=130),
        ]
        assert _tables_from_rules(_lines(runs), rules) == []

    def test_prose_in_a_ruled_box_is_not_a_table(self):
        """a boxed paragraph has rules and text but its cells are paragraphs."""
        rules = _mesh([40, 300, 560], [90, 260, 430])
        paragraph = (
            "At the University of Georgia everyone is held to a high level of "
            "academic honesty and the policy on plagiarism runs to a paragraph "
            "of some length in every syllabus that quotes it in full."
        )
        runs = [
            _run(paragraph, 50, 100, w=240),
            _run(paragraph, 310, 100, w=240),
            _run(paragraph, 50, 270, w=240),
            _run(paragraph, 310, 270, w=240),
        ]
        assert _tables_from_rules(_lines(runs), rules) == []

    def test_a_ghost_column_is_dropped(self):
        """a border drawn twice leaves an empty column band."""
        xs = [50, 54, 150, 300]  # 50 and 54: the same border, drawn twice
        rules = _mesh(xs, [100, 130, 160])
        runs = [
            _run("Week", 60, 110), _run("Topic", 160, 110),
            _run("1", 60, 140), _run("Introduction", 160, 140),
        ]
        tables = _tables_from_rules(_lines(runs), rules)
        assert len(tables) == 1
        assert tables[0] == [["Week", "Topic"], ["1", "Introduction"]]

    def test_a_title_bar_inside_the_box_is_trimmed(self):
        rules = _mesh([50, 150, 300], [70, 100, 130, 160])
        runs = [
            _run("Course Outline", 60, 80, w=200),
            _run("Week", 60, 110), _run("Topic", 160, 110),
            _run("1", 60, 140), _run("Introduction", 160, 140),
        ]
        tables = _tables_from_rules(_lines(runs), rules)
        assert len(tables) == 1
        assert tables[0][0] == ["Week", "Topic"]


class TestDefectsFoundInReview:
    """each of these produced wrong output before it was fixed."""

    def test_an_underline_in_a_cell_is_not_a_row_boundary(self):
        """a linked reading draws a rule under itself, inside the cell.

        taken as a row boundary it cut week one in half and left the reading
        below it in a row with no week and no topic, detached from its session.
        """
        rules = _mesh([90, 190, 340, 520], [100, 122, 220, 240])
        rules.append({"x0": 350, "y0": 163, "x1": 510, "y1": 163})
        runs = [
            _run("Week", 95, 105), _run("Topic", 195, 105), _run("Readings", 345, 105),
            _run("1", 95, 130), _run("Intro", 195, 130),
            _run("Smith ch. 1", 345, 130), _run("Jones, linked title", 345, 148),
            _run("Doe ch. 3", 345, 175),
            _run("2", 95, 225), _run("Methods", 195, 225), _run("Brown ch. 2", 345, 225),
        ]
        tables = _tables_from_rules(_lines(runs), rules)
        assert len(tables) == 1
        # three rows: the header and two weeks, with no phantom between them
        assert len(tables[0]) == 3
        assert [row[0] for row in tables[0]] == ["Week", "1", "2"]
        assert "Doe ch. 3" in tables[0][1][2]

    def test_two_tables_side_by_side_stay_apart(self):
        """they share row heights, and merging on the y alone fused them."""
        rules = _mesh([50, 160, 280], [100, 122, 144])
        rules += _mesh([330, 440, 560], [100, 122, 144])
        runs = [
            _run("Week", 55, 105), _run("Topic", 165, 105),
            _run("1", 55, 128), _run("Intro", 165, 128),
            _run("Item", 335, 105), _run("Pct", 445, 105),
            _run("Essay", 335, 128), _run("30%", 445, 128),
        ]
        tables = _tables_from_rules(_lines(runs), rules)
        assert len(tables) == 2
        assert [row[0] for row in tables[0]] == ["Week", "1"]
        assert [row[0] for row in tables[1]] == ["Item", "Essay"]

    def test_internal_separators_only_keeps_the_outer_columns(self):
        """no outer box: the first and last column were dropped entirely."""
        rules = [
            {"x0": 50, "y0": 100, "x1": 560, "y1": 100},
            {"x0": 50, "y0": 130, "x1": 560, "y1": 130},
            {"x0": 50, "y0": 160, "x1": 560, "y1": 160},
            {"x0": 180, "y0": 100, "x1": 180, "y1": 160},
            {"x0": 320, "y0": 100, "x1": 320, "y1": 160},
            {"x0": 450, "y0": 100, "x1": 450, "y1": 160},
        ]
        runs = [
            _run("Assignment", 60, 108), _run("Weight", 190, 108),
            _run("Due", 330, 108), _run("Notes", 460, 108),
            _run("Essay", 60, 138), _run("30%", 190, 138),
            _run("Oct 5", 330, 138), _run("in class", 460, 138),
        ]
        tables = _tables_from_rules(_lines(runs), rules)
        assert len(tables) == 1
        assert tables[0][0] == ["Assignment", "Weight", "Due", "Notes"]

    def test_a_header_with_no_rule_above_it_survives(self):
        """the verticals run up past the first horizontal; so does the header."""
        rules = [
            {"x0": 50, "y0": 130, "x1": 400, "y1": 130},
            {"x0": 50, "y0": 160, "x1": 400, "y1": 160},
            {"x0": 50, "y0": 190, "x1": 400, "y1": 190},
            {"x0": 50, "y0": 100, "x1": 50, "y1": 190},
            {"x0": 180, "y0": 100, "x1": 180, "y1": 190},
            {"x0": 400, "y0": 100, "x1": 400, "y1": 190},
        ]
        runs = [
            _run("Week", 60, 108), _run("Topic", 190, 108),
            _run("1", 60, 138), _run("Intro", 190, 138),
            _run("2", 60, 168), _run("Methods", 190, 168),
        ]
        tables = _tables_from_rules(_lines(runs), rules)
        assert len(tables) == 1
        assert tables[0][0] == ["Week", "Topic"]


class TestDocumentWiring:
    def _payload(self, rules):
        return {
            "filename": "t.pdf",
            "pages": [{
                "number": 1, "width": 612, "height": 792,
                "runs": [
                    {"text": "Week", "x": 60, "y": 110, "w": 40, "h": 10, "size": 10},
                    {"text": "Topic", "x": 160, "y": 110, "w": 40, "h": 10, "size": 10},
                    {"text": "1", "x": 60, "y": 140, "w": 10, "h": 10, "size": 10},
                    {"text": "Introduction", "x": 160, "y": 140, "w": 80, "h": 10, "size": 10},
                ],
                "rules": rules,
            }],
        }

    def test_rules_reach_the_page_tables(self):
        doc = document_from_runs(self._payload(_mesh([50, 150, 300], [100, 130, 160])))
        assert doc.pages[0].tables == [[["Week", "Topic"], ["1", "Introduction"]]]

    def test_a_payload_without_rules_still_parses(self):
        doc = document_from_runs(self._payload([]))
        assert doc.pages[0].text
        assert doc.pages[0].tables == []
