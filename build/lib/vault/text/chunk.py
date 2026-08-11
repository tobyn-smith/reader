"""split a document into segments that keep their page number.

the split follows paragraph and section boundaries rather than a character
count, because a quote is only useful if it can be cited, and a chunk that
starts mid sentence is hard to cite and hard to read back.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .model import ExtractedDoc

# a paragraph shorter than this is folded into its neighbour rather than
# becoming a chunk of its own
MIN_CHARS = 220
MAX_CHARS = 2200

_HEADING = re.compile(r"^\s*(?:\d+(?:\.\d+)*\s+)?[A-Z][A-Za-z .,:'-]{2,70}\s*$")


@dataclass
class Chunk:
    page_number: int
    ordinal: int
    body: str
    kind: str = "body"
    ref_marker: str | None = None


def chunk_document(doc: ExtractedDoc) -> list[Chunk]:
    chunks: list[Chunk] = []
    ordinal = 0
    carry = ""
    carry_page = 1

    for page in doc.pages:
        for paragraph in _paragraphs(page.text):
            if carry:
                paragraph = f"{carry}\n{paragraph}"
            else:
                carry_page = page.number

            if len(paragraph) < MIN_CHARS and not _HEADING.match(paragraph):
                carry = paragraph
                continue

            carry = ""
            for piece in _split_long(paragraph):
                chunks.append(Chunk(carry_page, ordinal, piece))
                ordinal += 1
            carry_page = page.number

        for note in page.footnotes:
            text = note.strip()
            if not text:
                continue
            chunks.append(
                Chunk(page.number, ordinal, text, kind="footnote", ref_marker=_marker(text))
            )
            ordinal += 1

    if carry.strip():
        chunks.append(Chunk(carry_page, ordinal, carry.strip()))

    return chunks


def _paragraphs(text: str) -> list[str]:
    blocks = re.split(r"\n\s*\n", text)
    out: list[str] = []
    for block in blocks:
        cleaned = "\n".join(line.rstrip() for line in block.splitlines() if line.strip())
        if cleaned.strip():
            out.append(cleaned.strip())
    return out


def _split_long(paragraph: str) -> list[str]:
    """a very long paragraph is cut at sentence ends, never mid sentence."""
    if len(paragraph) <= MAX_CHARS:
        return [paragraph]

    sentences = re.split(r"(?<=[.!?])\s+", paragraph)
    pieces: list[str] = []
    buffer = ""
    for sentence in sentences:
        if buffer and len(buffer) + len(sentence) + 1 > MAX_CHARS:
            pieces.append(buffer.strip())
            buffer = sentence
        else:
            buffer = f"{buffer} {sentence}".strip()
    if buffer.strip():
        pieces.append(buffer.strip())
    return pieces


def _marker(text: str) -> str | None:
    m = re.match(r"^\s*(\d{1,3})[.)\s]", text)
    return m.group(1) if m else None
