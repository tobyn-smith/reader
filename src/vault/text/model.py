"""the extracted document, independent of what did the extracting.

everything downstream of extraction works against these two classes and the
layout primitives, never against a pdf library. that is what lets the same
parser run on the command line over pymupdf output and in the browser over
text runs produced by a javascript extractor.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .normalize import Edit


@dataclass
class ExtractedPage:
    number: int
    text: str
    raw_text: str
    footnotes: list[str] = field(default_factory=list)
    tables: list[list[list[str]]] = field(default_factory=list)
    column_count: int = 1
    had_text_layer: bool = True
    edits: list[Edit] = field(default_factory=list)
    # text of each block in reading order. block boundaries survive because
    # "is this line the start of a block" is the cheapest reliable signal for
    # telling a heading from a wrapped line of prose.
    block_texts: list[str] = field(default_factory=list)

@dataclass
class ExtractedDoc:
    path: Path
    file_hash: str
    page_count: int
    pages: list[ExtractedPage]
    ocr_used: bool = False
    status: str = "ok"
    warnings: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n".join(p.text for p in self.pages)

    def page(self, number: int) -> ExtractedPage:
        return self.pages[number - 1]
