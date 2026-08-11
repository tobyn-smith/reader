"""geometry and repetition analysis over extracted pdf pages.

works on the block structures produced by extract.py rather than on raw strings,
because column order, footnote separation and header stripping all need
positions and font sizes to be decided correctly.
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field


@dataclass
class Block:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    size: float = 0.0

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2


@dataclass
class Page:
    number: int
    width: float
    height: float
    blocks: list[Block] = field(default_factory=list)
    # set once the page has been through column ordering
    column_count: int = 1

    @property
    def text(self) -> str:
        return "\n".join(b.text for b in self.blocks)


_DIGITS = re.compile(r"\d+")


def _shape(line: str) -> str:
    """collapse a line to what it looks like with the numbers taken out.

    a footer reading "Reyes 5" on one page and "Reyes 6" on the next is the same
    piece of furniture, so page numbers have to stop mattering before counting.
    """
    return _DIGITS.sub("#", " ".join(line.split())).strip().lower()


def detect_running_lines(
    pages: list[Page], *, edge_lines: int = 2, threshold: float = 0.6
) -> set[str]:
    """find the header and footer text repeated across most pages.

    only the top and bottom few lines of each page are candidates, so body text
    that happens to recur (a "Readings:" label on every week) is never caught.
    """
    if len(pages) < 3:
        return set()

    counts: dict[str, int] = {}
    for page in pages:
        lines = [ln for ln in page.text.splitlines() if ln.strip()]
        candidates = lines[:edge_lines] + lines[-edge_lines:]
        for shape in {_shape(ln) for ln in candidates if ln.strip()}:
            counts[shape] = counts.get(shape, 0) + 1

    needed = max(2, int(len(pages) * threshold))
    return {shape for shape, count in counts.items() if count >= needed and shape}


def strip_running_lines(page: Page, running: set[str]) -> Page:
    """drop header, footer and bare page-number lines from a page."""
    kept: list[Block] = []
    for block in page.blocks:
        lines = block.text.splitlines()
        surviving = [ln for ln in lines if not _is_furniture(ln, running)]
        if not surviving:
            continue
        kept.append(
            Block("\n".join(surviving), block.x0, block.y0, block.x1, block.y1, block.size)
        )
    return Page(page.number, page.width, page.height, kept, page.column_count)


def _is_furniture(line: str, running: set[str]) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if stripped.isdigit() and len(stripped) <= 4:
        return True
    return _shape(stripped) in running


def detect_columns(page: Page, *, min_blocks: int = 6) -> int:
    """return how many text columns the page is laid out in.

    the test is whether a vertical band down the middle of the page is clear.
    a two column article has almost nothing crossing it; a single column page
    has most of its blocks straddling it.
    """
    blocks = [b for b in page.blocks if b.text.strip()]
    if len(blocks) < min_blocks:
        return 1

    left = min(b.x0 for b in blocks)
    right = max(b.x1 for b in blocks)
    midline = (left + right) / 2
    band = (right - left) * 0.04

    crossing = sum(1 for b in blocks if b.x0 < midline - band and b.x1 > midline + band)
    on_left = sum(1 for b in blocks if b.x1 <= midline + band)
    on_right = sum(1 for b in blocks if b.x0 >= midline - band)

    if crossing / len(blocks) > 0.15:
        return 1
    if on_left >= 2 and on_right >= 2:
        return 2
    return 1


def order_blocks(page: Page) -> Page:
    """put blocks into reading order, one column at a time.

    interleaving columns is the classic way a two column pdf turns into
    unusable text, so this is the single most important thing in the file.
    """
    columns = detect_columns(page)
    blocks = [b for b in page.blocks if b.text.strip()]

    if columns == 1:
        ordered = sorted(blocks, key=lambda b: (round(b.y0, 1), b.x0))
    else:
        left_edge = min(b.x0 for b in blocks)
        right_edge = max(b.x1 for b in blocks)
        midline = (left_edge + right_edge) / 2
        left = sorted((b for b in blocks if b.cx < midline), key=lambda b: (b.y0, b.x0))
        right = sorted((b for b in blocks if b.cx >= midline), key=lambda b: (b.y0, b.x0))
        ordered = left + right

    return Page(page.number, page.width, page.height, ordered, columns)


_FOOTNOTE_START = re.compile(r"^\s*(\d{1,3})[.)\s]|^\s*[*†‡§]\s*")


def split_footnotes(page: Page) -> tuple[Page, list[Block]]:
    """separate footnote blocks from body blocks.

    footnotes are set smaller than body text and sit at the foot of the page.
    both signals are required, so a small caption in the middle of a page and a
    normal-size paragraph at the bottom are both left in the body.
    """
    blocks = [b for b in page.blocks if b.text.strip()]
    sizes = [b.size for b in blocks if b.size > 0]
    if not sizes:
        return page, []

    body_size = statistics.median(sizes)
    cutoff_y = page.height * 0.6

    body: list[Block] = []
    notes: list[Block] = []
    for block in blocks:
        smaller = block.size and block.size < body_size - 0.4
        low = block.y0 >= cutoff_y
        if smaller and low and _FOOTNOTE_START.match(block.text):
            notes.append(block)
        else:
            body.append(block)

    return Page(page.number, page.width, page.height, body, page.column_count), notes


def footnote_marker(block: Block) -> str | None:
    m = _FOOTNOTE_START.match(block.text)
    if not m:
        return None
    return (m.group(1) or m.group(0)).strip()
