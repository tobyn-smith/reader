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
from ..text.normalize import strip_leading_marker

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
            "thematic outline", "topical outline", "schedule and assignments",
            "course topics", "lecture schedule",
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
# a schedule headed by month and day rather than by week number. an optional
# list number in front, as in "1. August 14:", belongs to the list not the date.
_MONTH_LED = re.compile(
    # after the day, either punctuation or a capitalised (possibly quote
    # opened) topic. "Jan 13  Introduction" is a schedule line as surely as
    # "Jan 13: Introduction", and one syllabus wrote its whole calendar
    # without the colon. the >=3 matches guard downstream keeps prose that
    # happens to open with a date from starting the zone.
    r"^\s*(?:\(?\d{1,2}[.)]\s+)?"
    r"(?:jan|feb|mar|apr|may|jun|jul|aug|sept?|oct|nov|dec)[a-z]*\.?,?"
    # (?-i:) keeps the topic capital a real capital under the pattern's
    # IGNORECASE, or "jan 13 we will" style prose would match too
    r"\s*\d{1,2}\s*(?:st|nd|rd|th)?\s*(?:[:.–—-]|\s+(?-i:[\"“]?[A-Z]))",
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
    """one flat line list, with starts_block marking paragraph heads.

    two repairs to what "starts a block" means, both from real files. a block
    that opens with a whitespace-only line was giving starts_block to the
    blank and robbing its first real line of it. and some extractions hand
    back a whole page as one block, where the only structure left is the
    blank lines between paragraphs, so there a line following a blank one is
    a paragraph head. that second repair stays confined to oversized blocks:
    applied everywhere it split well-segmented schedules into phantom
    sessions, because a blank line inside a real block is spacing, not
    structure.
    """
    lines: list[Line] = []
    for page in doc.pages:
        blocks = page.block_texts or [page.text]
        for block in blocks:
            rows = block.splitlines()
            # degenerate means the extractor gave up and handed the whole
            # page over as one block. a long block on a page that otherwise
            # segmented fine is a real paragraph, and blank lines inside it
            # are spacing; treating those as paragraph heads let a mangled
            # summary grid seed phantom sessions.
            degenerate = len(blocks) == 1 and len(rows) > 15
            fresh = True
            for raw in rows:
                blank = not raw.strip()
                lines.append(Line(page.number, len(lines), raw, starts_block=fresh and not blank))
                # leading blanks keep the head available for the first real
                # line in any block; after that only a degenerate block lets
                # a blank re-arm it
                fresh = blank and (fresh or degenerate)
    return lines


_WEEK_NUMBER = re.compile(
    r"^\s*(?:week|session|class|unit|module)\s*#?\s*(\d{1,2})\b", re.IGNORECASE
)


def _first_week_of_the_schedule(lines: list[Line]) -> int | None:
    """find where the run of week headings starts.

    a syllabus names a week outside the schedule all the time: "Week 5
    Assignment (15%): due by midnight" sits in the requirements section, and
    starting the schedule there swallows the front matter. what distinguishes
    the real schedule is that its weeks form a long ascending run, so the
    longest such run wins and stray single mentions are ignored.
    """
    candidates: list[tuple[int, int]] = []
    for line in lines:
        # a week heading is routinely preceded by a bullet, and in some fonts
        # that bullet extracts as a stray letter on the same line
        m = _WEEK_NUMBER.match(strip_leading_marker(line.stripped)[0])
        if m:
            candidates.append((line.index, int(m.group(1))))

    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0][0]

    best_start, best_length = None, 0
    run_start, run_length = 0, 1
    for position in range(1, len(candidates)):
        # equal numbers are the same week meeting twice, which continues the run
        if candidates[position][1] >= candidates[position - 1][1]:
            run_length += 1
        else:
            run_start, run_length = position, 1
        if run_length > best_length:
            best_start, best_length = run_start, run_length

    if best_start is None or best_length < 2:
        return candidates[0][0]
    return candidates[best_start][0]


def find_schedule_start(lines: list[Line]) -> int | None:
    """locate where the week by week schedule begins.

    the structural signal, the first line that names a week, is trusted over
    heading keywords, because plenty of syllabi label the schedule with nothing
    more than a page break. when a schedule-ish heading sits just above that
    line it is taken as the real start so the heading is not left behind in the
    policy zone.
    """
    first_marker = _first_week_of_the_schedule(lines)

    if first_marker is None:
        for line in lines:
            text = strip_leading_marker(line.stripped)[0]
            if _DATE_LED.match(text):
                first_marker = line.index
                break

    if first_marker is None:
        # a month-led schedule. several are required before believing it, so a
        # sentence that happens to open with a date does not start the zone.
        dated = [line.index for line in lines
                 if _MONTH_LED.match(strip_leading_marker(line.stripped)[0])]
        if len(dated) >= 3:
            first_marker = dated[0]

    if first_marker is None:
        # no structural marker anywhere, so a keyword heading is the only hope.
        # the block gate is opened here: this fallback exists precisely for a
        # title-case "Course Schedule" heading, and one real syllabus buried
        # that heading mid-block behind policy prose, which left the whole
        # document as front matter and the parse with zero sessions.
        for line in lines:
            if is_heading(line.text, starts_block=True) and classify_heading(line.text) == SCHEDULE:
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

        # a keyword-classified line gets the title-case branch even mid-block.
        # the starts_block gate exists to keep wrapped prose from reading as a
        # heading, but a short title-case line that names a known zone is its
        # own evidence: "Grading" buried mid-block was costing a whole
        # requirements zone, and with it every weight in the course.
        heading = is_heading(
            line.text,
            starts_block=line.starts_block or classify_heading(line.text) is not None,
        )
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
