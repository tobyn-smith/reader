"""turn a pdf into pages of clean text, with page numbers kept throughout.

two extractors run over the same file. pymupdf handles flowing text and is what
almost everything downstream reads. pdfplumber is used only for pages that are
laid out as a table, because flowing extraction shreds those into unusable
interleaved fragments.

both results are kept. the syllabus parser decides which one to believe.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import warnings
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

from . import normalize
from .model import ExtractedDoc, ExtractedPage
from .layout import Block, Page, detect_running_lines, order_blocks, split_footnotes, strip_running_lines

warnings.filterwarnings("ignore", module="pdfplumber")
warnings.filterwarnings("ignore", module="pdfminer")

# a page with fewer than this many characters of text layer is treated as an
# image that needs ocr rather than a genuinely sparse page
MIN_CHARS_FOR_TEXT_LAYER = 40


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _blocks_for(page: pymupdf.Page) -> list[Block]:
    """pull text blocks with their box and dominant font size."""
    out: list[Block] = []
    data = page.get_text("dict")
    for block in data.get("blocks", []):
        if block.get("type") != 0:
            continue
        lines: list[str] = []
        sizes: list[float] = []
        for line in block.get("lines", []):
            spans = line.get("spans", [])
            lines.append("".join(span.get("text", "") for span in spans))
            sizes.extend(span.get("size", 0.0) for span in spans)
        text = "\n".join(lines)
        if not text.strip():
            continue
        x0, y0, x1, y1 = block["bbox"]
        size = max(set(sizes), key=sizes.count) if sizes else 0.0
        out.append(Block(text, x0, y0, x1, y1, size))
    return out


def extract_document(
    path: str | Path,
    *,
    ocr: str = "auto",
    detect_tables: bool = True,
    aggressive_spacing: bool = True,
) -> ExtractedDoc:
    path = Path(path)
    digest = file_hash(path)
    doc = pymupdf.open(path)

    scanned = [i + 1 for i, page in enumerate(doc) if len(page.get_text("text").strip()) < MIN_CHARS_FOR_TEXT_LAYER]

    ocr_used = False
    notes: list[str] = []
    if scanned and ocr in {"auto", "always"}:
        replacement = _run_ocr(path)
        if replacement is not None:
            doc.close()
            doc = pymupdf.open(replacement)
            ocr_used = True
            notes.append(f"ocr applied, pages without a text layer: {scanned}")
        else:
            notes.append(
                f"pages {scanned} have no text layer and ocrmypdf is not installed, "
                "so their text is missing rather than wrong"
            )

    raw_pages: list[Page] = []
    raw_text: list[str] = []
    for index, page in enumerate(doc):
        raw_text.append(page.get_text("text"))
        raw_pages.append(Page(index + 1, page.rect.width, page.rect.height, _blocks_for(page)))
    doc.close()

    running = detect_running_lines(raw_pages)
    tables = _extract_tables(path) if detect_tables else {}

    pages: list[ExtractedPage] = []
    for page in raw_pages:
        ordered = order_blocks(page)
        stripped = strip_running_lines(ordered, running)
        body, notes_blocks = split_footnotes(stripped)

        cleaned = normalize.clean_page_text(body.text, aggressive_spacing=aggressive_spacing)
        footnotes = [
            normalize.clean_page_text(b.text, aggressive_spacing=aggressive_spacing).text
            for b in notes_blocks
        ]
        block_texts = [
            normalize.clean_page_text(b.text, aggressive_spacing=aggressive_spacing).text
            for b in body.blocks
        ]
        pages.append(
            ExtractedPage(
                number=page.number,
                text=cleaned.text,
                raw_text=raw_text[page.number - 1],
                footnotes=footnotes,
                tables=tables.get(page.number, []),
                column_count=ordered.column_count,
                had_text_layer=page.number not in scanned or ocr_used,
                edits=cleaned.edits,
                block_texts=block_texts,
            )
        )

    status = "ok"
    if scanned and not ocr_used:
        status = "needs_ocr"

    return ExtractedDoc(
        path=path,
        file_hash=digest,
        page_count=len(pages),
        pages=pages,
        ocr_used=ocr_used,
        status=status,
        warnings=notes,
    )


def _run_ocr(path: Path) -> Path | None:
    """shell out to ocrmypdf, or give up cleanly if it is not installed.

    returns the path of a searchable copy, or None. never raises: a missing ocr
    toolchain degrades to "this page has no text", which is honest, rather than
    to invented text, which is not.
    """
    if shutil.which("ocrmypdf") is None:
        return None
    target = path.with_suffix(".ocr.pdf")
    try:
        subprocess.run(
            ["ocrmypdf", "--skip-text", "--quiet", str(path), str(target)],
            check=True,
            capture_output=True,
            timeout=900,
        )
    except (subprocess.SubprocessError, OSError):
        return None
    return target if target.exists() else None


def _extract_tables(path: Path) -> dict[int, list[list[list[str]]]]:
    """find ruled tables and return them as clean cell grids, keyed by page.

    pdfplumber derives column edges from the page rectangles, which on a real
    syllabus produces a handful of zero-width phantom columns between the real
    ones. dropping columns that are empty in every row is what turns a nine
    column result back into the three columns actually on the page.
    """
    try:
        import pdfplumber
    except ImportError:  # pragma: no cover - pdfplumber is a hard dependency
        return {}

    found: dict[int, list[list[list[str]]]] = {}
    with pdfplumber.open(path) as pdf:
        for index, page in enumerate(pdf.pages, start=1):
            grids: list[list[list[str]]] = []
            for table in page.find_tables():
                grid = _tidy_grid(table.extract())
                if _looks_like_a_real_table(grid):
                    grids.append(grid)
            if grids:
                found[index] = grids
    return found


def _tidy_grid(rows: list[list[str | None]]) -> list[list[str]]:
    if not rows:
        return []
    width = max(len(r) for r in rows)
    padded = [[(cell or "").strip() for cell in row] + [""] * (width - len(row)) for row in rows]

    keep = [i for i in range(width) if any(row[i] for row in padded)]
    trimmed = [[row[i] for i in keep] for row in padded]
    return [row for row in trimmed if any(cell for cell in row)]


def _looks_like_a_real_table(grid: list[list[str]]) -> bool:
    if len(grid) < 2:
        return False
    if not grid or len(grid[0]) < 2:
        return False
    filled = sum(1 for row in grid for cell in row if cell)
    return filled >= 4


