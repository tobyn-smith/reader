"""split a syllabus into functional zones.

everything downstream depends on this. reading-list parsing that strays into the
policy section invents readings out of prose, and deliverable parsing that never
reaches the requirements section misses most of the graded work, so this runs
first and is kept deliberately conservative.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..text.model import ExtractedDoc

FRONT_MATTER = "front_matter"
REQUIREMENTS = "requirements"
POLICIES = "policies"
SCHEDULE = "schedule"
APPENDIX = "appendix"


@dataclass
class Line:
    page: int
    index: int
    text: str
    starts_block: bool = False

    @property
    def stripped(self) -> str:
        return self.text.strip()


@dataclass
class Zone:
    kind: str
    heading: str | None
    lines: list[Line] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n".join(line.text for line in self.lines)

    @property
    def start_page(self) -> int:
        return self.lines[0].page if self.lines else 0


_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    (
        SCHEDULE,
        (
            "course outline", "class outline", "course schedule", "class schedule",
            "course calendar",
            "weekly schedule", "reading schedule", "schedule of readings",
            "schedule and assignments", "tentative schedule", "course overview",
            "weekly topics", "seminar schedule", "reading list", "course plan",
        ),
    ),
    (
        REQUIREMENTS,
        (
            "course requirements", "requirements and grading", "grading components",
            "grade distribution", "evaluation", "assessment", "graded work",
            "grading policy", "assignments and grading", "course assignments",
            "requirements", "grading", "grades",
        ),
    ),
    (
        POLICIES,
        (
            "university policies", "course policies", "policies", "academic honesty",
            "honor code", "attendance", "late work", "ferpa", "disability",
            "accommodation", "mental health", "wellness", "land acknowledgement",
            "land and labor", "title ix", "covid", "plagiarism", "artificial intelligence",
            "disclaimer", "administrative issues", "academic integrity", "netiquette",
        ),
    ),
    (APPENDIX, ("appendix", "bibliography", "further reading", "resources")),
]

# a numbered or lettered prefix on a heading, as in "3. Course Outline"
_HEADING_PREFIX = re.compile(r"^\s*(?:\d+[.)]|[ivxIVX]+[.)]|[A-Z][.)])\s*")

SESSION_MARKER = re.compile(
    r"^\s*(?:week|session|class|unit|module)\s*#?\s*\d{1,2}\b", re.IGNORECASE
)
_DATE_LED = re.compile(r"^\s*\d{1,2}\s*/\s*\d{1,2}\b")
# a schedule headed by month and day rather than by week number
_MONTH_LED = re.compile(
    r"^\s*(?:jan|feb|mar|apr|may|jun|jul|aug|sept?|oct|nov|dec)[a-z]*\.?"
    r"\s+\d{1,2}\s*(?:st|nd|rd|th)?\s*[:.–—-]",
    re.IGNORECASE,
)


def is_heading(text: str, *, starts_block: bool = False) -> bool:
    """a short line that introduces a section rather than being prose."""
    stripped = text.strip()
    if not stripped or len(stripped) > 90:
        return False
    if stripped.endswith((".", ",", ";", "?", "!")):
        return False
    words = stripped.split()
    if len(words) > 12:
        return False
    body = _HEADING_PREFIX.sub("", stripped).rstrip(":").strip()
    if not body:
        return False
    if body.isupper() and len(body) > 3:
        return True
    if stripped.endswith(":"):
        return True
    if _HEADING_PREFIX.match(stripped) and body[:1].isupper():
        return True

    # a title case line is only a heading when it opens a block. mid paragraph a
    # wrapped line can look identical, and treating those as headings shreds the
    # zones.
    if not starts_block or len(body) > 60 or not body[:1].isupper():
        return False
    alpha = re.findall(r"[A-Za-z][A-Za-z'’-]*", body)
    if not 1 <= len(alpha) <= 10:
        return False
    capitalised = sum(1 for word in alpha if word[:1].isupper())
    return capitalised / len(alpha) >= 0.6


def classify_heading(text: str) -> str | None:
    body = _HEADING_PREFIX.sub("", text.strip()).rstrip(":").strip().lower()
    if not body:
        return None
    for kind, keywords in _KEYWORDS:
        for keyword in keywords:
            if body == keyword or body.startswith(keyword) or keyword in body:
                return kind
    return None


def flatten(doc: ExtractedDoc) -> list[Line]:
    lines: list[Line] = []
    for page in doc.pages:
        blocks = page.block_texts or [page.text]
        for block in blocks:
            for offset, raw in enumerate(block.splitlines()):
                lines.append(Line(page.number, len(lines), raw, starts_block=offset == 0))
    return lines


def find_schedule_start(lines: list[Line]) -> int | None:
    """locate where the week by week schedule begins.

    the structural signal, the first line that names a week, is trusted over
    heading keywords, because plenty of syllabi label the schedule with nothing
    more than a page break. when a schedule-ish heading sits just above that
    line it is taken as the real start so the heading is not left behind in the
    policy zone.
    """
    first_marker = None
    for line in lines:
        text = line.stripped
        if SESSION_MARKER.match(text) or _DATE_LED.match(text):
            first_marker = line.index
            break

    if first_marker is None:
        # a month-led schedule. several are required before believing it, so a
        # sentence that happens to open with a date does not start the zone.
        dated = [line.index for line in lines if _MONTH_LED.match(line.stripped)]
        if len(dated) >= 3:
            first_marker = dated[0]

    if first_marker is None:
        for line in lines:
            if is_heading(line.text) and classify_heading(line.text) == SCHEDULE:
                return line.index
        return None

    # a schedule heading can sit well above the first week when a "what to do
    # each week" preamble or a table header row comes between them, so the
    # lookback is generous.
    lookback = max(0, first_marker - 40)
    for candidate in range(first_marker - 1, lookback - 1, -1):
        line = lines[candidate]
        if is_heading(line.text, starts_block=line.starts_block) and classify_heading(line.text) == SCHEDULE:
            return candidate
    return first_marker


def segment(doc: ExtractedDoc) -> list[Zone]:
    lines = flatten(doc)
    if not lines:
        return []

    schedule_start = find_schedule_start(lines)
    zones: list[Zone] = []
    current = Zone(FRONT_MATTER, None)
    in_schedule = False

    for line in lines:
        if schedule_start is not None and line.index == schedule_start:
            if current.lines:
                zones.append(current)
            current = Zone(SCHEDULE, line.stripped or None)
            current.lines.append(line)
            in_schedule = True
            continue

        heading = is_heading(line.text, starts_block=line.starts_block)
        kind = classify_heading(line.text) if heading else None

        # the schedule is the last major zone. once inside it, only an appendix
        # ends it: a numbered instruction inside a week is not a new section.
        if in_schedule:
            if kind == APPENDIX:
                zones.append(current)
                current = Zone(APPENDIX, line.stripped)
                in_schedule = False
        elif kind and kind != current.kind:
            if current.lines:
                zones.append(current)
            current = Zone(kind, line.stripped)
            in_schedule = kind == SCHEDULE

        current.lines.append(line)

    if current.lines:
        zones.append(current)
    return zones


def zone_text(zones: list[Zone], kind: str) -> str:
    return "\n".join(z.text for z in zones if z.kind == kind)


def zones_of(zones: list[Zone], kind: str) -> list[Zone]:
    return [z for z in zones if z.kind == kind]


def schedule_pages(doc: ExtractedDoc, zones: list[Zone]) -> list[int]:
    pages = {line.page for z in zones if z.kind == SCHEDULE for line in z.lines}
    return sorted(pages)
