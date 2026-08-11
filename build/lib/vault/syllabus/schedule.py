"""parse a schedule zone into sessions and their reading lists.

three layouts turn up often enough to need separate handling:

  bulleted  a week heading followed by one bullet per reading, where a single
            citation wraps over several lines with no indent to mark it
  table     a ruled grid of date, topic and assignments, which flowing text
            extraction shreds, so the cells are read instead
  labelled  a week heading followed by keyword blocks such as topic, readings,
            review, presentation, due

the structure is detected rather than configured, so a fourth layout degrades to
the closest match and reports low confidence instead of failing.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field

from ..text.model import ExtractedDoc
from ..text.normalize import collapse_whitespace, strip_leading_marker
from . import citations as cit
from .dates import DatedEntry, Term, iter_dates, parse_important_dates
from .zones import SCHEDULE, Line, Zone

BULLETED = "bulleted"
TABLE = "table"
LABELLED = "labelled"


@dataclass
class ReadingEntry:
    raw: str
    citation: cit.Citation
    requirement_level: str = "required"
    page_range: str | None = None
    access_note: str | None = None
    content_warning: str | None = None
    ordinal: int = 0

    @property
    def confidence(self) -> float:
        return self.citation.confidence


@dataclass
class SessionEntry:
    ordinal: int
    week_number: int | None = None
    meeting_date: dt.date | None = None
    sub_session_label: str | None = None
    topic: str | None = None
    section_heading: str | None = None
    session_type: str = "reading"
    page_number: int = 0
    raw: str = ""
    readings: list[ReadingEntry] = field(default_factory=list)
    # due and sign-up lines found inside the schedule, reconciled later against
    # the requirements zone
    deliverable_hints: list[str] = field(default_factory=list)
    confidence: float = 1.0


@dataclass
class ScheduleParse:
    structure: str
    sessions: list[SessionEntry] = field(default_factory=list)
    important_dates: list[DatedEntry] = field(default_factory=list)
    unparsed: list[str] = field(default_factory=list)


WEEK_RE = re.compile(
    r"^\s*(?:week|session|class|unit|module)\s*#?\s*(?P<number>\d{1,2})\b"
    r"\s*(?P<rest>.*)$",
    re.IGNORECASE,
)

# a keyword block label, as used by the labelled layout
LABEL_RE = re.compile(
    r"^\s*(?P<label>topic|readings?|review(?:\s*\([^)]*\))?|presentations?|due|"
    r"sign[\s-]?up|terms and key concepts|assignments?|watch|listen|optional|"
    r"recommended|required)\s*:\s*(?P<rest>.*)$",
    re.IGNORECASE,
)

# a line that cancels or replaces a meeting
NO_MEETING_RE = re.compile(
    r"\b(no class|no meeting|holiday|break|recess|cancelled|canceled)\b", re.IGNORECASE
)
EXAM_RE = re.compile(r"\b(exam|midterm|final)\b", re.IGNORECASE)
NO_READING_RE = re.compile(
    r"\b(no reading|syllabus review|course review|semester overview|"
    r"introduction and overview|guest speaker)\b",
    re.IGNORECASE,
)

# markers that split one week's material between two meetings
SUB_SESSION_RE = re.compile(
    r"^\s*(?:(?P<code>T|TR|TH|R|M|W|F|MW|TT?H)\s*:"
    r"|readings?\s+for\s+(?P<day>[A-Za-z]+)\s*:)\s*(?P<rest>.*)$",
    re.IGNORECASE,
)

CONTENT_WARNING_RE = re.compile(r"content\s+warning\s*:?\s*(?P<text>.+)$", re.IGNORECASE)
ACCESS_NOTE_RE = re.compile(
    r"((?:pdf|scan|copy|chapter|excerpt)[^.]{0,40}?\bon\b[^.]{0,40}"
    r"|available (?:on|at|through)[^.]{0,60}"
    r"|on reserve[^.]{0,40}"
    r"|provided by the instructor)",
    re.IGNORECASE,
)
PAGE_RANGE_RE = re.compile(
    r"\b(?:pp?\.|pages?|pgs?\.)\s*(\d+\s*[-‐-―]\s*\d+(?:\s*,\s*\d+\s*[-‐-―]\s*\d+)*)",
    re.IGNORECASE,
)

DELIVERABLE_HINT_RE = re.compile(
    r"^\s*(?:due|sign[\s-]?up|presentation|assessment|quiz|exam)\b|"
    r"\b(?:due|submit)\b.{0,40}\b\d{1,2}\s*/\s*\d{1,2}\b|"
    r"\bweekly assessment\b|\bassessment\s+\d+\b",
    re.IGNORECASE,
)

# a line that begins a fresh citation. surname then comma then a capital is the
# one signal that survives hanging indent, which inverts after the first line
# and so cannot be used.
CITATION_START_RE = re.compile(
    r"^\s*(?:"
    r"[A-Z][\w'’ÀÁÂÃÄÅÈÉÊËÌÍÎÏÒÓÔÕÖÙÚÛÜÝàáâãäåèéêëìíîïòóôõöùúûüýñÑçÇ-]+,\s+[A-Z]"
    r"|(?:chapters?|sections?|pages?|pp?\.|part)\b"
    r")"
)

_BARE_URL_RE = re.compile(r"^\s*(?:https?://|www\.)", re.IGNORECASE)


def _starts_new_entry(text: str, buffer: list[str]) -> bool:
    """decide whether a line opens a new reading or continues the one above.

    a url on its own line is usually the tail of the citation above, not a new
    reading, so it only counts as a new entry once the current one already has
    a url of its own. getting this wrong inflates a week's reading count, which
    is the failure mode counting tests exist to catch.
    """
    if CITATION_START_RE.match(text):
        return True
    if _BARE_URL_RE.match(text) and buffer:
        return any(_BARE_URL_RE.search(line) or "http" in line for line in buffer)
    return False


def detect_structure(doc: ExtractedDoc, zones: list[Zone]) -> str:
    pages = {line.page for z in zones if z.kind == SCHEDULE for line in z.lines}
    if any(doc.page(p).tables for p in pages if 1 <= p <= doc.page_count):
        if _table_looks_like_a_schedule(doc, pages):
            return TABLE

    lines = [line.stripped for z in zones if z.kind == SCHEDULE for line in z.lines]
    labelled = sum(1 for line in lines if LABEL_RE.match(line))
    bulleted = sum(1 for line in lines if strip_leading_marker(line)[1])

    if labelled >= 3 and labelled >= bulleted / 2:
        return LABELLED
    if bulleted >= 5:
        return BULLETED
    return LABELLED if labelled else BULLETED


def _table_looks_like_a_schedule(doc: ExtractedDoc, pages: set[int]) -> bool:
    for number in pages:
        if not 1 <= number <= doc.page_count:
            continue
        for grid in doc.page(number).tables:
            # cells carry their own newlines, so the probe has to be flattened
            # before anything can match across them
            flat = collapse_whitespace(" ".join(cell for row in grid for cell in row)).lower()
            if _WEEK_ANYWHERE_RE.search(flat):
                return True
            if re.search(r"\bdate\b.*\btopic\b", flat):
                return True
    return False


# the same week marker as WEEK_RE, but usable mid string rather than anchored
_WEEK_ANYWHERE_RE = re.compile(
    r"\b(?:week|session|class|unit|module)\s*#?\s*\d{1,2}\b", re.IGNORECASE
)


def parse(doc: ExtractedDoc, zones: list[Zone], term: Term | None) -> ScheduleParse:
    structure = detect_structure(doc, zones)
    lines = [line for z in zones if z.kind == SCHEDULE for line in z.lines]

    if structure == TABLE:
        result = _parse_table(doc, zones, term)
    elif structure == LABELLED:
        result = _parse_labelled(lines, term)
    else:
        result = _parse_bulleted(lines, term)

    result.important_dates = _find_important_dates(doc, term)
    return result


def _find_important_dates(doc: ExtractedDoc, term: Term | None) -> list[DatedEntry]:
    """read a standalone block of term dates wherever it appears."""
    for page in doc.pages:
        lines = page.text.splitlines()
        for index, line in enumerate(lines):
            if re.match(r"^\s*important dates\s*:?\s*$", line, re.IGNORECASE):
                return parse_important_dates(lines[index + 1: index + 24], term)
    return []


def _new_session(ordinal: int, page: int, raw: str) -> SessionEntry:
    return SessionEntry(ordinal=ordinal, page_number=page, raw=raw)


def _classify_session(session: SessionEntry) -> None:
    """decide what kind of meeting this is, without inventing readings.

    a week with nothing assigned is a real thing: a break, an exam, a review, an
    instructor away at a conference. recording that is the point, so nothing here
    ever falls back to treating an empty week as a parse failure.
    """
    blob = " ".join([session.raw, session.topic or ""])
    if session.readings:
        session.session_type = "reading"
        return
    if NO_MEETING_RE.search(blob):
        session.session_type = "holiday"
    elif EXAM_RE.search(blob):
        session.session_type = "exam"
    elif re.search(r"\bpresentation", blob, re.IGNORECASE):
        session.session_type = "presentation"
    elif re.search(r"\bassignment week\b", blob, re.IGNORECASE):
        session.session_type = "assignment"
    elif NO_READING_RE.search(blob):
        session.session_type = "no_reading"
    else:
        session.session_type = "no_reading"


def _split_week_heading(session: SessionEntry, text: str, term: Term | None) -> None:
    m = WEEK_RE.match(text)
    if m:
        session.week_number = int(m.group("number"))
        rest = m.group("rest")
    else:
        rest = text

    found = list(iter_dates(rest, term))
    if found:
        session.meeting_date = found[0]

    topic = rest
    topic = re.sub(r"^\s*[(\[]?\s*\d{1,2}\s*/\s*\d{1,2}\s*[)\]]?", "", topic)
    topic = re.sub(
        r"^[\s,:.-]*(?:[A-Za-z]+\s+\d{1,2}(?:st|nd|rd|th)?)[\s,:.-]*", "", topic
    )
    topic = topic.strip(" :,-–—")
    # a malformed date such as "January 6h" leaves its stray letter behind
    topic = re.sub(r"^[a-z]\b\s*", "", topic).strip(" :,-–—")
    session.topic = collapse_whitespace(topic) or None


def _finish(session: SessionEntry, entries: list[str]) -> None:
    ordinal = 0
    for raw in entries:
        entry = _build_reading(raw, ordinal)
        if entry is None:
            continue
        session.readings.append(entry)
        ordinal += 1
    _classify_session(session)
    if session.readings:
        session.confidence = min(r.confidence for r in session.readings)


def _build_reading(raw: str, ordinal: int) -> ReadingEntry | None:
    text = collapse_whitespace(raw)
    if not text or len(text) < 4:
        return None
    if cit.looks_like_placeholder(text):
        return None
    # an instruction is not a reading. "syllabus review, no reading" under a
    # week heading means the week has none, and an exam announcement is an
    # event. inventing a reading from either would make the status view lie
    # about what is outstanding.
    if NO_READING_RE.search(text) or NO_MEETING_RE.search(text) or EXAM_RE.search(text):
        if not cit.parse_citation(text).parsed or len(text) < 60:
            return None

    working = text
    warning = None
    m = CONTENT_WARNING_RE.search(working)
    if m:
        warning = collapse_whitespace(m.group("text"))
        working = working[: m.start()].strip(" •-–—")

    access = None
    m = ACCESS_NOTE_RE.search(working)
    if m:
        access = collapse_whitespace(m.group(1)).strip(" .")
        working = (working[: m.start()] + " " + working[m.end():]).strip()

    pages = None
    m = PAGE_RANGE_RE.search(working)
    if m:
        pages = collapse_whitespace(m.group(1))

    citation = cit.parse_citation(working)
    return ReadingEntry(
        raw=text,
        citation=citation,
        page_range=pages,
        access_note=access,
        content_warning=warning,
        ordinal=ordinal,
    )


def _parse_bulleted(lines: list[Line], term: Term | None) -> ScheduleParse:
    """a week heading, then one bullet per reading.

    citations wrap over several lines with nothing to mark the continuation, so
    entries are split on the bullet marker and never on the newline.
    """
    result = ScheduleParse(BULLETED)
    session: SessionEntry | None = None
    buffer: list[str] = []
    current: list[str] = []
    section_heading: str | None = None

    def flush_entry() -> None:
        if current:
            buffer.append(" ".join(current))
            current.clear()

    def flush_session() -> None:
        nonlocal session
        flush_entry()
        if session is not None:
            _finish(session, buffer)
            result.sessions.append(session)
        buffer.clear()
        session = None

    for line in lines:
        text = line.stripped
        if not text:
            continue

        stripped, marker = strip_leading_marker(text)
        heading_candidate = stripped if marker else text

        if WEEK_RE.match(heading_candidate):
            flush_session()
            session = _new_session(len(result.sessions), line.page, heading_candidate)
            session.section_heading = section_heading
            _split_week_heading(session, heading_candidate, term)
            continue

        if session is None:
            if _looks_like_unit_heading(text):
                section_heading = text.strip(" :")
            continue

        if DELIVERABLE_HINT_RE.match(stripped) and not marker:
            session.deliverable_hints.append(stripped)
            continue

        if marker:
            flush_entry()
            current.append(stripped)
        else:
            current.append(text)

    flush_session()
    return result


def _looks_like_unit_heading(text: str) -> bool:
    return bool(re.match(r"^\s*(unit|part|module|section)\b", text, re.IGNORECASE))


def _parse_labelled(lines: list[Line], term: Term | None) -> ScheduleParse:
    """a week heading, then keyword blocks."""
    result = ScheduleParse(LABELLED)
    session: SessionEntry | None = None
    entries: list[tuple[str, str]] = []
    current: list[str] = []
    label = "readings"

    def flush_entry() -> None:
        if current:
            joined = collapse_whitespace(" ".join(current))
            if joined:
                entries.append((label, joined))
            current.clear()

    def flush_session() -> None:
        nonlocal session, label
        flush_entry()
        if session is not None:
            _finish_labelled(session, entries)
            result.sessions.append(session)
        entries.clear()
        session = None
        label = "readings"

    for line in lines:
        text = line.stripped
        if not text:
            flush_entry()
            continue

        if WEEK_RE.match(text):
            flush_session()
            session = _new_session(len(result.sessions), line.page, text)
            _split_week_heading(session, text, term)
            continue

        # a dated line with no week number, such as a break or a cancelled class
        if session is not None and NO_MEETING_RE.search(text) and list(iter_dates(text, term)):
            flush_session()
            standalone = _new_session(len(result.sessions), line.page, text)
            found = list(iter_dates(text, term))
            standalone.meeting_date = found[0] if found else None
            standalone.topic = collapse_whitespace(re.sub(r"[-–—]", " ", text))
            standalone.session_type = "holiday"
            result.sessions.append(standalone)
            continue

        if session is None:
            continue

        m = LABEL_RE.match(text)
        if m:
            flush_entry()
            label = m.group("label").strip().lower()
            rest = m.group("rest").strip()
            if label == "topic":
                session.topic = collapse_whitespace(rest) or session.topic
                continue
            if label in {"due", "sign-up", "sign up", "signup", "presentation", "presentations"}:
                if rest:
                    session.deliverable_hints.append(f"{label}: {rest}")
                continue
            if rest:
                current.append(rest)
            continue

        if label in {"due", "sign-up", "sign up", "signup", "presentation", "presentations"}:
            session.deliverable_hints.append(f"{label}: {text}")
            continue

        if _starts_new_entry(text, current):
            flush_entry()
        current.append(text)

    flush_session()
    return result


def _finish_labelled(session: SessionEntry, tagged: list[tuple[str, str]]) -> None:
    ordinal = 0
    for label, raw in tagged:
        entry = _build_reading(raw, ordinal)
        if entry is None:
            continue
        entry.requirement_level = _requirement_level(label)
        session.readings.append(entry)
        ordinal += 1
    _classify_session(session)
    if session.readings:
        session.confidence = min(r.confidence for r in session.readings)


def _requirement_level(label: str) -> str:
    label = label.lower()
    if "inspectional" in label:
        return "inspectional"
    if label.startswith("review"):
        return "review"
    if label.startswith("recommend") or label.startswith("optional"):
        return "recommended"
    if label.startswith("terms"):
        return "reference"
    return "required"


def _parse_table(doc: ExtractedDoc, zones: list[Zone], term: Term | None) -> ScheduleParse:
    """read the cells rather than the flowing text.

    a row whose first cell has no week and no date is a continuation of the row
    above, which is what a week split across a page break looks like.
    """
    result = ScheduleParse(TABLE)
    pages = sorted({line.page for z in zones if z.kind == SCHEDULE for line in z.lines})

    rows: list[tuple[int, list[str]]] = []
    for number in pages:
        if not 1 <= number <= doc.page_count:
            continue
        for grid in doc.page(number).tables:
            for row in grid:
                cleaned = _strip_header_labels(row)
                if not any(cleaned):
                    continue
                rows.append((number, cleaned))

    for page, row in rows:
        first = collapse_whitespace(row[0]) if row else ""
        has_anchor = bool(WEEK_RE.match(first) or list(iter_dates(first, term)))
        if not has_anchor and result.sessions:
            _append_to_last(result.sessions, row)
            continue
        if not has_anchor:
            continue
        _row_to_sessions(result, page, row, term)

    for session in result.sessions:
        _classify_session(session)
    return result


_HEADER_LABEL_RE = re.compile(
    r"^\s*(?:date|week|day|topic|theme|subject|"
    r"assignments?(?:\s+and\s+due\s+dates?)?|due(?:\s+dates?)?|"
    r"readings?|notes?|deadlines?)\s*:?\s*$",
    re.IGNORECASE,
)


def _strip_header_labels(row: list[str]) -> list[str]:
    """remove a column heading from the top of each cell.

    cell extraction gives the heading its own row, while reconstructing a table
    from text positions can fold it into the first data row, because the gap
    below a heading is no bigger than the gap between lines inside a cell. the
    label is therefore removed wherever it turns up, and the row is dropped only
    when nothing survives. a heading never carries a number, so "Week 1" is
    untouched.
    """
    out: list[str] = []
    for cell in row:
        lines = cell.split("\n")
        while lines and _HEADER_LABEL_RE.match(lines[0]):
            lines.pop(0)
        out.append("\n".join(lines).strip())
    return out


def _row_to_sessions(
    result: ScheduleParse, page: int, row: list[str], term: Term | None
) -> None:
    anchor = row[0]
    topic = row[1] if len(row) > 1 else ""
    body = row[2] if len(row) > 2 else ""
    if len(row) == 2:
        topic, body = "", row[1]

    # a date cell stacks the week and its meeting dates on separate lines, so it
    # has to be flattened before the week pattern can see past the first newline
    week = WEEK_RE.match(collapse_whitespace(anchor))
    week_number = int(week.group("number")) if week else None
    dates = list(iter_dates(anchor, term))

    blocks = _split_sub_sessions(body)
    if not blocks:
        blocks = [(None, "")]

    for index, (label, chunk) in enumerate(blocks):
        session = _new_session(len(result.sessions), page, f"{anchor} | {topic} | {chunk}".strip())
        session.week_number = week_number
        session.topic = collapse_whitespace(topic) or None
        session.sub_session_label = label
        if dates:
            session.meeting_date = dates[min(index, len(dates) - 1)]
        entries, hints = _split_cell_entries(chunk)
        session.deliverable_hints = hints
        _finish(session, entries)
        result.sessions.append(session)


def _append_to_last(sessions: list[SessionEntry], row: list[str]) -> None:
    tail = " ".join(cell for cell in row if cell).strip()
    if not tail:
        return
    session = sessions[-1]
    entries, hints = _split_cell_entries(tail)
    session.deliverable_hints.extend(hints)
    start = len(session.readings)
    for offset, raw in enumerate(entries):
        entry = _build_reading(raw, start + offset)
        if entry is not None:
            session.readings.append(entry)


def _split_sub_sessions(cell: str) -> list[tuple[str | None, str]]:
    """split one cell into the meetings it covers.

    a course meeting twice a week labels each half, so the two halves become two
    sessions rather than one merged reading list.
    """
    lines = cell.splitlines()
    blocks: list[tuple[str | None, list[str]]] = []
    current_label: str | None = None
    current: list[str] = []

    for line in lines:
        m = SUB_SESSION_RE.match(line)
        if m:
            if current or blocks:
                blocks.append((current_label, current))
                current = []
            code = m.group("code") or m.group("day") or ""
            current_label = code.strip().upper() or None
            rest = m.group("rest").strip()
            if rest:
                current.append(rest)
            continue
        current.append(line)

    blocks.append((current_label, current))
    out = [(label, "\n".join(body).strip()) for label, body in blocks if "\n".join(body).strip()]
    return out


def _split_cell_entries(chunk: str) -> tuple[list[str], list[str]]:
    """turn a cell into reading entries and deliverable hints.

    entries inside a cell are separated by blank lines. a bullet that follows an
    entry is a qualifier on it, such as a content warning, so it is folded back
    into the entry above rather than becoming a reading of its own.
    """
    entries: list[str] = []
    hints: list[str] = []
    buffer: list[str] = []

    def flush() -> None:
        joined = collapse_whitespace(" ".join(buffer))
        buffer.clear()
        if not joined:
            return
        if DELIVERABLE_HINT_RE.match(joined) and not CITATION_START_RE.match(joined):
            hints.append(joined)
        else:
            entries.append(joined)

    for line in chunk.splitlines():
        text = line.strip()
        if not text:
            flush()
            continue
        stripped, marker = strip_leading_marker(text)
        if marker and buffer and CONTENT_WARNING_RE.search(stripped):
            buffer.append(stripped)
            continue
        if DELIVERABLE_HINT_RE.match(text) and not CITATION_START_RE.match(text):
            flush()
            hints.append(collapse_whitespace(text))
            continue
        # cells do not always keep the blank line between entries, so a line
        # that clearly opens a citation also ends the previous one
        if _starts_new_entry(text, buffer):
            flush()
        buffer.append(text)

    flush()
    return entries, hints
