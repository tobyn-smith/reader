"""build an ExtractedDoc from positioned text runs.

this is the contract between a javascript pdf extractor and the python parser.
the browser hands over json shaped like:

    {"pages": [{"number": 1, "width": 612, "height": 792,
                "runs": [{"text": "Week 1", "x": 72, "y": 96,
                          "w": 40, "h": 11, "size": 11}, ...]}],
     "filename": "syllabus.pdf", "sha256": "..."}

y grows downward, like pdf.js viewport coordinates and like layout.py expects.
no pdf library is imported here, which is the point: the same code runs under
pyodide in a browser tab and in ordinary cpython for the parity tests.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from pathlib import Path

from . import normalize
from .layout import Block, Page, detect_running_lines, order_blocks, split_footnotes, strip_running_lines
from .model import ExtractedDoc, ExtractedPage

MIN_CHARS_FOR_TEXT_LAYER = 40


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
            if cursor is not None:
                gap = run.x - cursor
                # a space is roughly a quarter of the font size. measured
                # against real syllabi, anything above about 0.28 starts gluing
                # words together, which turned "u Week 1 (8/14)" into
                # "uWeek1(8/14)" and hid every week heading from the parser.
                threshold = max(run.size, 4.0) * 0.25
                if gap > threshold and parts and not parts[-1].endswith(" ") and not run.text.startswith(" "):
                    parts.append(" ")
            parts.append(run.text)
            cursor = max(cursor, run.x1) if cursor is not None else run.x1
        return "".join(parts)


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
        return []

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

    anchor_ys = sorted(y for y, _, column, _ in fragments if column == 0)
    if len(anchor_ys) < 2:
        return []

    heights = [h for _, h, _, _ in fragments if h > 0]
    line_height = statistics.median(heights) if heights else 12.0

    # group anchor lines into rows. two shapes exist: a grid with one line per
    # row, where anchor lines sit at uniform single-line spacing, and a grid
    # whose date cell stacks a week above its meeting dates, where lines inside
    # a cell sit closer than lines across a row boundary. uniform spacing means
    # every anchor line is its own row; otherwise only a gap well beyond line
    # spacing starts one.
    gaps = [b - a for a, b in zip(anchor_ys, anchor_ys[1:])]
    uniform = gaps and statistics.median(gaps) <= line_height * 1.7

    if uniform:
        rows = list(anchor_ys)
    else:
        rows = [anchor_ys[0]]
        previous = anchor_ys[0]
        for y in anchor_ys[1:]:
            if y - previous > line_height * 2.4:
                rows.append(y)
            previous = y
    if len(rows) < 2:
        return []

    def row_of(y: float) -> int:
        row = 0
        for index, top in enumerate(rows):
            if y >= top - 3.0:
                row = index
        return row

    grid: list[list[list[str]]] = [[[] for _ in edges] for _ in rows]
    for y, _, column, text in sorted(fragments):
        grid[row_of(y)][column].append(text)

    table = [["\n".join(cell).strip() for cell in row] for row in grid]
    table = [row for row in table if any(row)]
    filled = sum(1 for row in table for cell in row if cell)
    if len(table) < 2 or filled < 4:
        return []
    return [table]


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
    missing_text: list[int] = []

    for entry in payload.get("pages", []):
        number = int(entry.get("number", len(raw_pages) + 1))
        width = float(entry.get("width", 612))
        height = float(entry.get("height", 792))
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
            tables = [
                [
                    [normalize.clean_page_text(cell, aggressive_spacing=aggressive_spacing).text
                     for cell in row]
                    for row in grid
                ]
                for grid in _tables_from_lines(page_lines[page.number], page.width)
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
