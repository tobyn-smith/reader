"""build an ExtractedDoc from positioned text runs.

this is the contract between a javascript pdf extractor and the python parser.
the browser hands over json shaped like:

    {"pages": [{"number": 1, "width": 612, "height": 792,
                "runs": [{"text": "Week 1", "x": 72, "y": 96,
                          "w": 40, "h": 11, "size": 11}, ...],
                "rules": [{"x0": 70, "y0": 90, "x1": 540, "y1": 90}, ...]}],
     "filename": "syllabus.pdf", "sha256": "..."}

y grows downward, like pdf.js viewport coordinates and like layout.py expects.
no pdf library is imported here, which is the point: the same code runs under
pyodide in a browser tab and in ordinary cpython for the parity tests.

"rules" is optional and carries the ruled line segments a page draws its
tables with, axis aligned, already in the same top-down space as the runs.
where they exist the table grid is read straight off them, the way pdfplumber
reads it on the command line; where they are absent or say nothing, table
recovery falls back to clustering the text positions alone.
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass
from pathlib import Path

from . import normalize
from .layout import Block, Page, detect_running_lines, order_blocks, split_footnotes, strip_running_lines
from .model import ExtractedDoc, ExtractedPage

MIN_CHARS_FOR_TEXT_LAYER = 40

# a week heading inside a table's anchor column. defined here rather than
# imported because text/ sits below syllabus/ and must not depend on it.
_WEEK_MARK_RE = re.compile(r"^\s*(?:week|session|module|unit)\s*#?\s*\d{1,2}\b", re.IGNORECASE)

# schedule table header vocabulary, split into the column that carries time and
# the columns that carry content. same layering note as above.
_TIME_HEADER_RE = re.compile(
    r"^(?:week|wk|date|dates|day|days|meetings?|class(?:es)?|session)\b", re.IGNORECASE
)
_CONTENT_HEADER_RE = re.compile(
    r"^(?:topic|theme|subject|unit|readings?|assignments?|homework|materials?|"
    r"due|deliverables?|notes?|other\s*due|material\s*due)\b",
    re.IGNORECASE,
)


@dataclass
class Run:
    text: str
    x: float
    y: float
    w: float
    h: float
    size: float

    @property
    def x1(self) -> float:
        return self.x + self.w

    @property
    def y1(self) -> float:
        return self.y + self.h


@dataclass
class Line:
    runs: list[Run]

    @property
    def x0(self) -> float:
        return min(r.x for r in self.runs)

    @property
    def x1(self) -> float:
        return max(r.x1 for r in self.runs)

    @property
    def y0(self) -> float:
        return min(r.y for r in self.runs)

    @property
    def y1(self) -> float:
        return max(r.y1 for r in self.runs)

    @property
    def size(self) -> float:
        sizes = [r.size for r in self.runs if r.size]
        return statistics.median(sizes) if sizes else 0.0

    @property
    def text(self) -> str:
        """join runs left to right, inserting the spaces kerning removed.

        a gap wider than a third of the font size between two runs is a word
        break. narrower gaps are letter spacing inside a word.
        """
        ordered = sorted(self.runs, key=lambda r: r.x)
        parts: list[str] = []
        cursor = None
        for run in ordered:
            em = max(run.size, 4.0)

            # a column gap can arrive as a run that is nothing but whitespace
            # yet many times wider than a space. keeping it as one character
            # throws away the only sign that a label and its number are in
            # separate columns, which is what the weights table is read from.
            if run.text and not run.text.strip():
                width = max(run.w, run.x1 - (cursor or run.x))
                parts.append(" " * _space_run(width, em))
                cursor = max(cursor, run.x1) if cursor is not None else run.x1
                continue

            if cursor is not None:
                gap = run.x - cursor
                # a space is roughly a quarter of the font size. measured
                # against real syllabi, anything above about 0.28 starts gluing
                # words together, which turned "u Week 1 (8/14)" into
                # "uWeek1(8/14)" and hid every week heading from the parser.
                if gap > em * 0.25 and parts and not parts[-1].endswith(" ") and not run.text.startswith(" "):
                    parts.append(" " * _space_run(gap, em))
            parts.append(run.text)
            cursor = max(cursor, run.x1) if cursor is not None else run.x1
        return "".join(parts)


def _space_run(width: float, em: float) -> int:
    """how many spaces a blank of this width stands for.

    one space for an ordinary word break, several for a column gap, so that
    text laid out in columns still reads as columns downstream.
    """
    if width <= em * 0.6:
        return 1
    return max(2, min(12, int(width / (em * 0.35))))


def _lines_from_runs(runs: list[Run]) -> list[Line]:
    """group runs into lines by vertical overlap.

    two runs share a line when their vertical centres are within half a line
    height of each other. pdf.js emits runs in stream order, which is not
    reading order, so this works purely from geometry.
    """
    todo = sorted((r for r in runs if r.text.strip()), key=lambda r: (r.y, r.x))
    lines: list[Line] = []
    for run in todo:
        centre = (run.y + run.y1) / 2
        tolerance = max(run.h, run.size, 6.0) * 0.55
        for line in reversed(lines[-8:]):
            line_centre = (line.y0 + line.y1) / 2
            if abs(centre - line_centre) <= tolerance:
                line.runs.append(run)
                break
        else:
            lines.append(Line([run]))
    lines.sort(key=lambda l: (l.y0, l.x0))
    return lines


def _blocks_from_lines(lines: list[Line]) -> list[Block]:
    """group lines into blocks on vertical gaps.

    a gap taller than 0.85 of the running line height starts a new block, which
    matches how paragraphs and headings separate on a page.
    """
    blocks: list[Block] = []
    current: list[Line] = []

    def flush() -> None:
        if not current:
            return
        text = "\n".join(line.text for line in current)
        sizes = [line.size for line in current if line.size]
        blocks.append(
            Block(
                text,
                min(l.x0 for l in current),
                min(l.y0 for l in current),
                max(l.x1 for l in current),
                max(l.y1 for l in current),
                statistics.median(sizes) if sizes else 0.0,
            )
        )
        current.clear()

    previous: Line | None = None
    for line in lines:
        if previous is not None:
            height = max(previous.y1 - previous.y0, line.size, 8.0)
            gap = line.y0 - previous.y1
            same_column = line.x0 < previous.x1 and previous.x0 < line.x1
            if gap > height * 0.85 or (not same_column and gap < -height):
                flush()
        current.append(line)
        previous = line
    flush()
    return blocks


def _run_edges_behind_header(lines: list[Line]) -> tuple[list[float], float, int] | None:
    """find a grid that fits each row on one line, gated by its header.

    line-start clustering cannot see these grids: every line begins at the left
    margin. run-start clustering can, but it also sees phantom tables in
    hanging-indent citation lists, which is worse than missing a grid. the gate
    is the header row: a real schedule grid names its columns, and a line whose
    fragments include a time word and a content word in different columns is
    accepted as that header. citation lists have no such line.

    returns (edges, header line y, time column index) or None.
    """
    xs = sorted(run.x for line in lines for run in line.runs if run.text.strip())
    if len(xs) < 12:
        return None

    clusters: list[list[float]] = []
    for x in xs:
        if clusters and x - clusters[-1][-1] <= 14:
            clusters[-1].append(x)
        else:
            clusters.append([x])
    edges = [statistics.median(c) for c in clusters if len(c) >= 3]
    if len(edges) < 3 or len(edges) > 7:
        return None
    if max(edges) - min(edges) < 160:
        return None

    bounds = [(edges[i] + edges[i + 1]) / 2 for i in range(len(edges) - 1)]

    def column_of(x: float) -> int:
        for index, boundary in enumerate(bounds):
            if x < boundary:
                return index
        return len(edges) - 1

    for line in lines[:20]:
        by_column: dict[int, list[Run]] = {}
        for run in line.runs:
            by_column.setdefault(column_of(run.x), []).append(run)
        if len(by_column) < 2:
            continue
        time_cols = []
        content_cols = []
        for column, runs in sorted(by_column.items()):
            text = Line(runs).text.strip()
            if len(text) > 40:
                continue
            # run joining loses spaces in tight headers, so split the camel
            probe = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", text)
            if _TIME_HEADER_RE.match(probe):
                time_cols.append(column)
            elif _CONTENT_HEADER_RE.match(probe):
                content_cols.append(column)
        if time_cols and content_cols and len(time_cols) + len(content_cols) >= 2:
            # a grid with both a week and a date column keys its rows on the
            # denser one: weeks repeat across two meetings, dates do not
            def density(column: int) -> int:
                return sum(
                    1
                    for other in lines
                    if other.y0 > line.y0 + 3.0
                    and any(column_of(r.x) == column for r in other.runs)
                )

            best = max(time_cols, key=density)
            return edges, line.y0, best

    return None


def _tables_from_lines(lines: list[Line], page_width: float) -> list[list[list[str]]]:
    """rebuild a ruled table from run positions alone.

    the browser extractor carries no ruled-line information, so structure is
    recovered in three steps: column edges from the x positions where text
    starts, cell fragments by splitting each line's runs at those edges, and
    row boundaries by grouping anchor-column fragments that sit close together,
    because one schedule row's date cell is itself several stacked lines.
    """
    if len(lines) < 8:
        return []

    edges = _column_edges(lines)
    if len(edges) < 2:
        gated = _run_edges_behind_header(lines)
        if gated is None:
            return []
        return _grid_from_header_gate(lines, *gated)

    # boundaries midway between edges. a run belongs to the column whose band
    # holds its start, wrapped continuation indents included.
    bounds = [(edges[i] + edges[i + 1]) / 2 for i in range(len(edges) - 1)]

    def column_of(x: float) -> int:
        for index, boundary in enumerate(bounds):
            if x < boundary:
                return index
        return len(edges) - 1

    # fragment: one line's runs inside one column
    fragments: list[tuple[float, float, int, str]] = []  # y0, height, column, text
    for line in lines:
        by_column: dict[int, list[Run]] = {}
        for run in line.runs:
            by_column.setdefault(column_of(run.x), []).append(run)
        for column, runs in by_column.items():
            text = Line(runs).text.strip()
            if text:
                fragments.append((line.y0, line.y1 - line.y0, column, text))

    anchor = sorted((y, text) for y, _, column, text in fragments if column == 0)
    if len(anchor) < 2:
        return []
    anchor_ys = [y for y, _ in anchor]

    heights = [h for _, h, _, _ in fragments if h > 0]
    line_height = statistics.median(heights) if heights else 12.0

    # group anchor lines into rows. measured against real schedules, lines
    # inside one cell sit at up to about 2.5 line heights apart, while true row
    # boundaries sit at 8 or more, so 3.5 splits them with a wide margin.
    # week markers are a stronger signal than any gap: where the anchor column
    # says "Week 1", "Week 2", rows start exactly there, everything above the
    # first marker is preamble, and a dated row far below the last line (a
    # final exam row) still opens its own.
    gaps = [b - a for a, b in zip(anchor_ys, anchor_ys[1:])]
    uniform = gaps and statistics.median(gaps) <= line_height * 1.7
    week_marks = [y for y, text in anchor if _WEEK_MARK_RE.match(text)]

    # two markers on one page is a schedule; a prose page names a week once
    rows: list[float]
    if len(week_marks) >= 2:
        rows = []
        previous = None
        for y, text in anchor:
            if _WEEK_MARK_RE.match(text):
                rows.append(y)
            elif rows and previous is not None and y - previous > line_height * 3.5:
                rows.append(y)
            previous = y
    elif uniform:
        rows = list(anchor_ys)
    else:
        rows = [anchor_ys[0]]
        previous = anchor_ys[0]
        for y in anchor_ys[1:]:
            if y - previous > line_height * 3.5:
                rows.append(y)
            previous = y
    if len(rows) < 2:
        return []

    def row_of(y: float) -> int:
        # a fragment above the first row is page furniture, not table content
        if y < rows[0] - 3.0:
            return -1
        row = 0
        for index, top in enumerate(rows):
            if y >= top - 3.0:
                row = index
        return row

    grid: list[list[list[str]]] = [[[] for _ in edges] for _ in rows]
    for y, _, column, text in sorted(fragments):
        target = row_of(y)
        if target >= 0:
            grid[target][column].append(text)

    table = [["\n".join(cell).strip() for cell in row] for row in grid]
    table = [row for row in table if any(row)]
    filled = sum(1 for row in table for cell in row if cell)
    if len(table) < 2 or filled < 4:
        return []
    return [table]


def _grid_from_header_gate(
    lines: list[Line], edges: list[float], header_y: float, time_col: int
) -> list[list[list[str]]]:
    """build the grid for a header-gated one-line-per-row table.

    rows start at the header and at every fragment in the time column below it.
    lines without time-column content fold into the row above, which is what a
    wrapped cell looks like. everything above the header is page furniture.
    """
    bounds = [(edges[i] + edges[i + 1]) / 2 for i in range(len(edges) - 1)]

    def column_of(x: float) -> int:
        for index, boundary in enumerate(bounds):
            if x < boundary:
                return index
        return len(edges) - 1

    fragments: list[tuple[float, int, str]] = []
    for line in lines:
        by_column: dict[int, list[Run]] = {}
        for run in line.runs:
            by_column.setdefault(column_of(run.x), []).append(run)
        for column, runs in by_column.items():
            text = Line(runs).text.strip()
            if text:
                fragments.append((line.y0, column, text))

    rows = [header_y] + sorted(
        y for y, column, _ in fragments if column == time_col and y > header_y + 3.0
    )

    def row_of(y: float) -> int:
        if y < rows[0] - 3.0:
            return -1
        row = 0
        for index, top in enumerate(rows):
            if y >= top - 3.0:
                row = index
        return row

    grid: list[list[list[str]]] = [[[] for _ in edges] for _ in rows]
    for y, column, text in sorted(fragments):
        target = row_of(y)
        if target >= 0:
            grid[target][column].append(text)

    table = [["\n".join(cell).strip() for cell in row] for row in grid]
    table = [row for row in table if any(row)]
    filled = sum(1 for row in table for cell in row if cell)
    if len(table) < 3 or filled < 6:
        return []
    return [table]


def _tables_from_rules(
    lines: list[Line], rules: list[dict]
) -> list[list[list[str]]]:
    """rebuild tables from the ruled lines the page actually drew.

    this is the ground truth the command line has always had through
    pdfplumber, and the reason it read grading tables the browser could not.
    horizontal rules are row boundaries, vertical rules are column boundaries,
    and a cell is whatever text falls inside the rectangle they enclose.
    nothing is inferred: a grid is claimed only where at least three of each
    intersect, which a decorative box around a paragraph cannot fake.
    """
    horizontals: list[tuple[float, float, float]] = []  # y, x0, x1
    verticals: list[tuple[float, float, float]] = []  # x, y0, y1
    for rule in rules:
        try:
            x0 = float(rule["x0"])
            y0 = float(rule["y0"])
            x1 = float(rule["x1"])
            y1 = float(rule["y1"])
        except (KeyError, TypeError, ValueError):
            continue
        if abs(y1 - y0) <= 0.7 and x1 - x0 >= 6:
            horizontals.append(((y0 + y1) / 2, x0, x1))
        elif abs(x1 - x0) <= 0.7 and y1 - y0 >= 6:
            verticals.append(((x0 + x1) / 2, y0, y1))

    if len(horizontals) < 3 or len(verticals) < 3:
        return []

    # rules at the same coordinate drawn as several dashes, or once per cell,
    # merge into one boundary carrying the union of their extents. they have to
    # touch to merge: two tables printed side by side share their row heights,
    # and merging on the coordinate alone joined them into one grid whose
    # columns interleaved two different tables.
    def merge(
        segments: list[tuple[float, float, float]], tolerance: float
    ) -> list[tuple[float, float, float]]:
        merged: list[tuple[float, float, float]] = []
        for key, lo, hi in sorted(segments):
            joined = False
            for index, (prev_key, prev_lo, prev_hi) in enumerate(merged):
                if abs(key - prev_key) <= tolerance and lo <= prev_hi + 12 and hi >= prev_lo - 12:
                    merged[index] = (prev_key, min(prev_lo, lo), max(prev_hi, hi))
                    joined = True
                    break
            if not joined:
                merged.append((key, lo, hi))
        return merged

    row_lines = merge(horizontals, 2.5)
    col_lines = merge(verticals, 2.5)

    tables: list[list[list[str]]] = []
    used_rows: set[int] = set()
    while True:
        # seed a table from the topmost unused row line and gather everything
        # connected to it, so two separate tables on one page stay separate
        seed = next(
            (i for i, _ in enumerate(row_lines) if i not in used_rows), None
        )
        if seed is None:
            break
        rows = [seed]
        changed = True
        while changed:
            changed = False
            y_min = min(row_lines[i][0] for i in rows)
            y_max = max(row_lines[i][0] for i in rows)
            x_min = min(row_lines[i][1] for i in rows)
            x_max = max(row_lines[i][2] for i in rows)
            cols = [
                (x, lo, hi)
                for x, lo, hi in col_lines
                if x_min - 4 <= x <= x_max + 4
                and lo <= y_max + 4
                and hi >= y_min - 4
            ]
            if cols:
                span_lo = min(lo for _, lo, _ in cols)
                span_hi = max(hi for _, _, hi in cols)
                for i, (y, lo, hi) in enumerate(row_lines):
                    if i in rows or i in used_rows:
                        continue
                    if span_lo - 4 <= y <= span_hi + 4 and hi >= x_min - 4 and lo <= x_max + 4:
                        rows.append(i)
                        changed = True
        used_rows.update(rows)

        # a row boundary runs most of the way across the table. a hyperlink
        # underline drawn inside one cell is also a horizontal rule, and taking
        # it as a boundary cut a real row in half and stranded the reading
        # under it in a row with no week and no topic.
        width = max(row_lines[i][2] for i in rows) - min(row_lines[i][1] for i in rows)
        spanning = [
            i for i in rows
            if width <= 0 or (row_lines[i][2] - row_lines[i][1]) >= width * 0.6
        ]
        row_ys = sorted(row_lines[i][0] for i in spanning)
        if len(row_ys) < 3 or len(cols) < 3:
            continue

        # a table is a mesh: its verticals cross its horizontals. hyperlink
        # underlines fail this completely, and they are everywhere in a
        # syllabus: a reading list of linked titles draws a horizontal rule
        # under every link, and one stray vertical was enough to mint a
        # phantom grid over a page of prose citations.
        row_set = [row_lines[i] for i in rows]
        crossings = sum(
            1
            for y, rx0, rx1 in row_set
            for x, cy0, cy1 in cols
            if rx0 - 3 <= x <= rx1 + 3 and cy0 - 3 <= y <= cy1 + 3
        )
        if crossings < 0.45 * len(row_set) * len(cols):
            continue

        col_xs = sorted(x for x, _, _ in cols)

        # plenty of tables draw only their internal separators: no outer box,
        # or no rule above the header. the missing outer boundaries are taken
        # from how far the rules themselves reach, so the first and last
        # columns and the header row are not dropped for want of a line.
        left = min(row_lines[i][1] for i in spanning)
        right = max(row_lines[i][2] for i in spanning)
        if col_xs[0] - left > 4:
            col_xs.insert(0, left)
        if right - col_xs[-1] > 4:
            col_xs.append(right)
        top = min(lo for _, lo, _ in cols)
        bottom = max(hi for _, _, hi in cols)
        if row_ys[0] - top > 4:
            row_ys.insert(0, top)
        if bottom - row_ys[-1] > 4:
            row_ys.append(bottom)

        grid = _grid_from_boundaries(lines, row_ys, col_xs)
        if grid is not None and _looks_like_a_table(grid):
            tables.append(grid)

    return tables


def _looks_like_a_table(grid: list[list[str]]) -> bool:
    """decide whether a ruled region held a table or just ruled decoration.

    letterheads, sidebars and boxed policy statements draw plenty of rules,
    and reading those boxes as tables swallowed whole pages of prose: one
    document came back with every paragraph filed into a three column grid
    and its real schedule drowned among them. the discriminator is the cells:
    table cells are short, prose poured into a box is not.
    """
    filled = [cell for row in grid for cell in row if cell.strip()]
    if len(filled) < 4:
        return False
    lengths = sorted(len(cell) for cell in filled)
    median = lengths[len(lengths) // 2]
    if median > 90:
        return False
    # one enormous cell is a paragraph in a box, whatever the median says
    if lengths[-1] > 700:
        return False
    return True


def _grid_from_boundaries(
    lines: list[Line], row_ys: list[float], col_xs: list[float]
) -> list[list[str]] | None:
    """fill a boundary grid with the text that falls inside each cell."""
    grid = [
        [[] for _ in range(len(col_xs) - 1)] for _ in range(len(row_ys) - 1)
    ]

    def band(value: float, boundaries: list[float]) -> int | None:
        # half a point of slack: a run drawn exactly on a rule belongs inside
        if value < boundaries[0] - 0.5 or value > boundaries[-1] + 0.5:
            return None
        for index in range(len(boundaries) - 1):
            if value <= boundaries[index + 1]:
                return index
        return len(boundaries) - 2

    filled = 0
    for line in lines:
        for run in line.runs:
            if not run.text.strip():
                continue
            row = band(run.y + run.h / 2, row_ys)
            col = band(run.x + min(run.w, 4.0) / 2, col_xs)
            if row is None or col is None:
                continue
            grid[row][col].append(run)

    # a border drawn twice, or a drop shadow beside it, makes a ghost column
    # that holds nothing. the shape detector counts columns, so a six column
    # schedule wearing two empty ghosts stops looking like itself.
    keep = [
        index for index in range(len(col_xs) - 1) if any(row[index] for row in grid)
    ]
    if len(keep) < 2:
        return None
    grid = [[row[index] for index in keep] for row in grid]
    kept_bounds = [col_xs[index + 1] for index in keep]

    # a title bar drawn inside the table box arrives as a leading row whose one
    # cell of text runs across the column boundary, sometimes with an empty
    # spacer row under it. the header the shape detector needs is below them.
    while grid:
        populated = [index for index, cell in enumerate(grid[0]) if cell]
        if not populated:
            grid.pop(0)
            continue
        if len(populated) == 1:
            index = populated[0]
            spans = any(
                run.x1 > kept_bounds[index] + 4 for run in grid[0][index]
            )
            if spans or len(grid[0]) >= 3:
                grid.pop(0)
                continue
        break
    while grid and not any(cell for cell in grid[-1]):
        grid.pop()
    if len(grid) < 2:
        return None

    cells: list[list[str]] = []
    for row in grid:
        rendered: list[str] = []
        for cell_runs in row:
            if not cell_runs:
                rendered.append("")
                continue
            cell_lines = _lines_from_runs(list(cell_runs))
            rendered.append("\n".join(l.text.strip() for l in cell_lines).strip())
            filled += 1
        cells.append(rendered)

    # a grid of empty cells is a drawing, not a table
    if filled < 4:
        return None
    return cells


def _column_edges(lines: list[Line]) -> list[float]:
    """cluster line-start x positions into stable column edges.

    line starts, deliberately. clustering run starts instead would also see the
    grids that fit a whole row on one line, but hanging-indent citation lists
    produce equally stable run-start columns, and treating those pages as
    tables shreds them. a missed table degrades to flowing text; a phantom
    table destroys a document. the conservative side of that trade is the only
    acceptable one.
    """
    xs = sorted(line.x0 for line in lines)
    clusters: list[list[float]] = []
    for x in xs:
        if clusters and x - clusters[-1][-1] <= 14:
            clusters[-1].append(x)
        else:
            clusters.append([x])
    edges = [statistics.median(c) for c in clusters if len(c) >= 3]
    if not edges:
        return []
    # a paragraph produces one big cluster at the margin. a table needs several
    # populated edges spread across the page.
    if len(edges) < 2:
        return []
    span = max(edges) - min(edges)
    if span < 120:
        return []
    return edges[:6]


def document_from_runs(
    payload: dict, *, aggressive_spacing: bool = True, detect_tables: bool = True
) -> ExtractedDoc:
    raw_pages: list[Page] = []
    page_lines: dict[int, list[Line]] = {}
    page_rules: dict[int, list[dict]] = {}
    missing_text: list[int] = []

    for entry in payload.get("pages", []):
        number = int(entry.get("number", len(raw_pages) + 1))
        width = float(entry.get("width", 612))
        height = float(entry.get("height", 792))
        page_rules[number] = list(entry.get("rules") or [])
        runs = [
            Run(
                text=str(r.get("text", "")),
                x=float(r.get("x", 0)),
                y=float(r.get("y", 0)),
                w=float(r.get("w", 0)),
                h=float(r.get("h", r.get("size", 0) or 0)),
                size=float(r.get("size", 0) or 0),
            )
            for r in entry.get("runs", [])
        ]
        lines = _lines_from_runs(runs)
        page_lines[number] = lines
        blocks = _blocks_from_lines(lines)
        if sum(len(b.text.strip()) for b in blocks) < MIN_CHARS_FOR_TEXT_LAYER:
            missing_text.append(number)
        raw_pages.append(Page(number, width, height, blocks))

    running = detect_running_lines(raw_pages)

    pages: list[ExtractedPage] = []
    for page in raw_pages:
        ordered = order_blocks(page)
        stripped = strip_running_lines(ordered, running)
        body, note_blocks = split_footnotes(stripped)

        cleaned = normalize.clean_page_text(body.text, aggressive_spacing=aggressive_spacing)
        footnotes = [
            normalize.clean_page_text(b.text, aggressive_spacing=aggressive_spacing).text
            for b in note_blocks
        ]
        block_texts = [
            normalize.clean_page_text(b.text, aggressive_spacing=aggressive_spacing).text
            for b in body.blocks
        ]

        tables: list[list[list[str]]] = []
        if detect_tables:
            # ruled lines are the drawn structure and outrank any guess made
            # from text positions; the clustering fallback only runs where the
            # page drew nothing usable
            grids = _tables_from_rules(page_lines[page.number], page_rules.get(page.number, []))
            if not grids:
                grids = _tables_from_lines(page_lines[page.number], page.width)
            tables = [
                [
                    [normalize.clean_page_text(cell, aggressive_spacing=aggressive_spacing).text
                     for cell in row]
                    for row in grid
                ]
                for grid in grids
            ]

        pages.append(
            ExtractedPage(
                number=page.number,
                text=cleaned.text,
                raw_text="\n".join(line.text for line in page_lines[page.number]),
                footnotes=footnotes,
                tables=tables,
                column_count=ordered.column_count,
                had_text_layer=page.number not in missing_text,
                edits=cleaned.edits,
                block_texts=block_texts,
            )
        )

    warnings: list[str] = []
    status = "ok"
    if missing_text:
        status = "needs_ocr"
        warnings.append(f"pages without a text layer: {missing_text}")

    return ExtractedDoc(
        path=Path(payload.get("filename", "document.pdf")),
        file_hash=payload.get("sha256", ""),
        page_count=len(pages),
        pages=pages,
        status=status,
        warnings=warnings,
    )
