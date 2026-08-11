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
from ..text.normalize import URL_RE, collapse_whitespace, strip_leading_marker
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

# plenty of syllabi number nothing and head each meeting with its date instead:
# "January 17th: Module 1: Introduction". a separator or a capitalised
# continuation is required so a sentence that merely opens with a date is not
# mistaken for a heading.
DATE_HEADING_RE = re.compile(
    r"^\s*(?P<date>(?:jan|feb|mar|apr|may|jun|jul|aug|sept?|oct|nov|dec)[a-z]*\.?"
    r"\s+\d{1,2}\s*(?:st|nd|rd|th)?)"
    r"\s*(?:[:.–—-]\s*(?P<rest>.*)|\s+(?P<rest2>[A-Z].*))$",
    re.IGNORECASE,
)


def date_heading(text: str) -> re.Match[str] | None:
    """match a date-led session heading, if the line is one."""
    if len(text) > 160:
        return None
    return DATE_HEADING_RE.match(text)


def is_session_head(text: str, *, starts_block: bool = True) -> bool:
    """a week marker anywhere, or a date heading that opens a block.

    a week marker is unambiguous. a date-led heading is not: prose inside a
    week can begin with a date too, so it only counts where a block starts,
    which is where a heading actually sits.
    """
    if WEEK_RE.match(text):
        return True
    return starts_block and date_heading(text) is not None

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


def count_date_headings(lines: list[str]) -> int:
    return sum(1 for line in lines if date_heading(line))


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
            # a header row that names a time column and a content column is a
            # schedule regardless of the exact words it chose
            shape = _shape_from_header(grid)
            if shape.from_header and (
                shape.week_col is not None or shape.date_cols
            ) and (shape.topic_col is not None or shape.body_cols):
                return True

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
        dated = date_heading(text)
        if dated:
            rest = dated.group("rest") or dated.group("rest2") or ""
            found = list(iter_dates(dated.group("date"), term))
            if found:
                session.meeting_date = found[0]
            session.topic = collapse_whitespace(rest).strip(" :,-–—") or None
            return
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

    if _is_fragment(working):
        return None

    citation = cit.parse_citation(working)
    return ReadingEntry(
        raw=text,
        citation=citation,
        page_range=pages,
        access_note=access,
        content_warning=warning,
        ordinal=ordinal,
    )


def _is_fragment(text: str) -> bool:
    """a leftover piece of a url rather than a reading.

    a long url wrapped inside a table cell can survive as two pieces, and the
    tail looks like an entry of its own: ".org/details/foo/page/n9" or
    "mode/2up". listing those as assigned readings is worse than dropping them,
    because a checklist of things that were never assigned is unusable.
    """
    stripped = text.strip()
    if stripped[:1] in {".", "/", "-", "?", "&", "="}:
        return True

    # "Chapter 2" or "pp. 12-30" is terse but it is a real assignment
    if re.match(r"(?i)^(?:chapters?|ch\.?|pages?|pp?\.?|parts?|sections?|units?)\s*\d", stripped):
        return False

    # what is left once every url is removed. a real citation keeps words.
    without_urls = URL_RE.sub(" ", stripped)
    words = re.findall(r"[A-Za-z]{3,}", without_urls)
    if len(words) >= 3:
        return False
    # nothing but a url, or a couple of path words, is not a citation
    return len(" ".join(words)) < 12


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

        if is_session_head(heading_candidate, starts_block=line.starts_block):
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


# "Section II: Historical and International Perspectives" groups the weeks that
# follow. it is a heading, not an assignment, and not part of whatever label it
# happens to sit under.
UNIT_HEADING_RE = re.compile(
    r"^\s*(?:unit|part|module|section)\s+(?:[IVXLC]+|\d{1,2}|[A-Z])\s*[:.–-]",
    re.IGNORECASE,
)


def _looks_like_unit_heading(text: str) -> bool:
    return bool(UNIT_HEADING_RE.match(text))


def _parse_labelled(lines: list[Line], term: Term | None) -> ScheduleParse:
    """a week heading, then keyword blocks."""
    result = ScheduleParse(LABELLED)
    session: SessionEntry | None = None
    entries: list[tuple[str, str]] = []
    current: list[str] = []
    label = "readings"
    section_heading: str | None = None

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

        if is_session_head(text, starts_block=line.starts_block):
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

        # a unit heading ends whatever block is open. without this it is
        # swallowed by the label above it and surfaces as a phantom deadline.
        if _looks_like_unit_heading(text):
            flush_entry()
            section_heading = text.strip(" :")
            if session is not None:
                label = "readings"
            continue

        if session is None:
            continue

        if session.section_heading is None:
            session.section_heading = section_heading

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


@dataclass
class TableShape:
    """which column holds what, learned from the header row.

    a schedule table is not always date, topic, readings. real ones run to six
    columns (week, date, unit, topic, material due, other due), and reading
    positionally there put a date in the topic and threw the readings away.
    when no header names the columns, the old positional reading stands.
    """

    week_col: int | None = None
    date_cols: list[int] = field(default_factory=list)
    topic_col: int | None = None
    unit_col: int | None = None
    body_cols: list[int] = field(default_factory=list)
    from_header: bool = False


_WEEK_HEADERS = re.compile(r"^\s*(?:week|wk|meetings?|class(?:es)?|session)\s*:?\s*$", re.IGNORECASE)
_DATE_HEADERS = re.compile(r"^\s*(?:date|dates|day|days)\b[^|]*$", re.IGNORECASE)
_TOPIC_HEADERS = re.compile(r"^\s*(?:topic|theme|subject)s?\s*:?\s*$", re.IGNORECASE)
_UNIT_HEADERS = re.compile(r"^\s*(?:unit|module|section|part)s?\s*:?\s*$", re.IGNORECASE)
_BODY_HEADERS = re.compile(
    r"^\s*(?:readings?|assignments?|homework|materials?|notes?|deliverables?|"
    r"assignments?\s+and\s+due\s+dates?|(?:material|other|work)\s*due|"
    r"due(?:\s+dates?)?|what.?s\s+due)\s*(?:\([^)]*\))?\s*:?\s*$",
    re.IGNORECASE,
)


def _shape_from_header(grid: list[list[str]]) -> TableShape:
    shape = TableShape()
    if not grid:
        return shape

    header = [collapse_whitespace(cell.split("\n")[0]) for cell in grid[0]]
    recognised = 0
    for index, label in enumerate(header):
        if _WEEK_HEADERS.match(label) and shape.week_col is None:
            shape.week_col, recognised = index, recognised + 1
        elif _DATE_HEADERS.match(label):
            shape.date_cols.append(index)
            recognised += 1
        elif _TOPIC_HEADERS.match(label) and shape.topic_col is None:
            shape.topic_col, recognised = index, recognised + 1
        elif _UNIT_HEADERS.match(label) and shape.unit_col is None:
            shape.unit_col, recognised = index, recognised + 1
        elif _BODY_HEADERS.match(label):
            shape.body_cols.append(index)
            recognised += 1

    # two named columns is a header row. one could be a stray word.
    if recognised >= 2:
        shape.from_header = True
        # a "meetings" style column carries both the week number and the date
        if shape.week_col is not None and not shape.date_cols:
            shape.date_cols = [shape.week_col]
        if shape.from_header and shape.topic_col is None and shape.unit_col is not None:
            shape.topic_col, shape.unit_col = shape.unit_col, None
        return shape

    return TableShape()


_BARE_WEEK_INT = re.compile(r"^\s*(\d{1,2})\s*$")
# a date written month-dash-day, as in "01-07". only believed in an anchor
# cell: anywhere else two digits around a dash is a page range.
_DASH_DATE = re.compile(r"\b(\d{1,2})-(\d{1,2})\b")


def _anchor_dates(text: str, term: Term | None) -> list:
    found = list(iter_dates(text, term))
    if found or term is None or len(text) > 24:
        return found
    out = []
    for m in _DASH_DATE.finditer(text):
        month, day = int(m.group(1)), int(m.group(2))
        if 1 <= month <= 12 and 1 <= day <= 31:
            built = _safe_term_date(term, month, day)
            if built:
                out.append(built)
    return out


def _safe_term_date(term: Term, month: int, day: int):
    import datetime as _dt

    try:
        return _dt.date(term.year_for_month(month), month, day)
    except ValueError:
        return None


def _parse_table(doc: ExtractedDoc, zones: list[Zone], term: Term | None) -> ScheduleParse:
    """read the cells rather than the flowing text.

    the header row, when there is one, decides which column holds the week, the
    date, the topic and the work. a row with a date but no week continues the
    week above it as a second meeting; a row with neither continues the same
    meeting, which is what a row split across a page break looks like.
    """
    result = ScheduleParse(TABLE)
    pages = sorted({line.page for z in zones if z.kind == SCHEDULE for line in z.lines})

    # the shape belongs to a grid, not to the document. pdfplumber reports a
    # different column geometry page by page, phantom columns included, so a
    # shape learned on one page misreads the next. a headerless grid inherits
    # the previous shape only when the widths agree, which is what a table
    # continuing across a page break looks like.
    previous: TableShape | None = None
    previous_width = 0
    rows: list[tuple[int, list[str], TableShape]] = []
    for number in pages:
        if not 1 <= number <= doc.page_count:
            continue
        for grid in doc.page(number).tables:
            width = max(len(r) for r in grid) if grid else 0
            shape = _shape_from_header(grid)
            if not shape.from_header:
                if previous is not None and previous.from_header and width == previous_width:
                    shape = previous
            previous, previous_width = shape, width
            for row in grid:
                cleaned = _strip_header_labels(row)
                if not any(cleaned):
                    continue
                rows.append((number, cleaned, shape))

    last_week: int | None = None
    for page, row, shape in rows:
        week_number, dates = _row_anchor(row, shape, term)

        if week_number is None and not dates:
            if result.sessions:
                _append_to_last(result.sessions, row, shape)
            continue

        if week_number is None and dates and shape.from_header:
            # a dated row under the same week: the second meeting of the week
            week_number = last_week
        if week_number is not None:
            last_week = week_number

        _row_to_sessions(result, page, row, term, shape, week_number, dates)

    for session in result.sessions:
        _classify_session(session)
    return result


def _row_anchor(
    row: list[str], shape: TableShape, term: Term | None
) -> tuple[int | None, list]:
    """what week and dates anchor this row, if any."""
    if shape.from_header:
        week_number = None
        if shape.week_col is not None and shape.week_col < len(row):
            cell = collapse_whitespace(row[shape.week_col])
            bare = _BARE_WEEK_INT.match(cell)
            if bare and 1 <= int(bare.group(1)) <= 20:
                week_number = int(bare.group(1))
            else:
                named = WEEK_RE.match(cell)
                if named:
                    week_number = int(named.group("number"))
        dates = []
        for col in shape.date_cols:
            if col < len(row):
                dates.extend(_anchor_dates(collapse_whitespace(row[col]), term))
        if week_number is None:
            # plenty of tables stack "Week 1" above the dates inside the date
            # column rather than giving weeks a column of their own
            for col in shape.date_cols:
                if col < len(row):
                    named = WEEK_RE.match(collapse_whitespace(row[col]))
                    if named:
                        week_number = int(named.group("number"))
                        break
        return week_number, dates

    first = collapse_whitespace(row[0]) if row else ""
    named = WEEK_RE.match(first)
    return (int(named.group("number")) if named else None), list(iter_dates(first, term))


_HEADER_LABEL_RE = re.compile(
    r"^\s*(?:date|dates|week|day|days|topic|theme|subject|meetings?|unit|module|"
    r"assignments?(?:\s+and\s+due\s+dates?)?|due(?:\s+dates?)?|"
    r"(?:material|other|work)\s*due|"
    r"readings?|notes?|deadlines?|materials?)\s*(?:\([^)]*\))?\s*:?\s*$",
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


def _row_cells(row: list[str], shape: TableShape) -> tuple[str, str, str, str]:
    """pull anchor, topic, unit and body text out of a row using the shape.

    topic and date columns never reach the reading list. that separation is
    structural rather than a filter: a cell the header called "Topic" cannot
    leak into the readings no matter what it contains.
    """
    if shape.from_header:
        def cell(index: int | None) -> str:
            return row[index] if index is not None and index < len(row) else ""

        anchor_cols = {shape.week_col, *shape.date_cols} - {None}
        anchor = "\n".join(cell(i) for i in sorted(anchor_cols))
        topic = cell(shape.topic_col)
        unit = cell(shape.unit_col)
        if shape.body_cols:
            body = "\n\n".join(cell(i) for i in shape.body_cols if cell(i))
        else:
            named = anchor_cols | {shape.topic_col, shape.unit_col}
            body = "\n\n".join(
                row[i] for i in range(len(row)) if i not in named and row[i]
            )
        return anchor, topic, unit, body

    anchor = row[0] if row else ""
    topic = row[1] if len(row) > 1 else ""
    body = row[2] if len(row) > 2 else ""
    if len(row) == 2:
        topic, body = "", row[1]
    return anchor, topic, "", body


def _row_to_sessions(
    result: ScheduleParse,
    page: int,
    row: list[str],
    term: Term | None,
    shape: TableShape,
    week_number: int | None,
    dates: list,
) -> None:
    anchor, topic, unit, body = _row_cells(row, shape)

    blocks = _split_sub_sessions(body)
    if not blocks:
        blocks = [(None, "")]

    for index, (label, chunk) in enumerate(blocks):
        session = _new_session(len(result.sessions), page, f"{anchor} | {topic} | {chunk}".strip())
        session.week_number = week_number
        session.topic = collapse_whitespace(topic) or None
        session.section_heading = collapse_whitespace(unit) or None
        session.sub_session_label = label
        if dates:
            session.meeting_date = dates[min(index, len(dates) - 1)]
        entries, hints = _split_cell_entries(chunk)
        session.deliverable_hints = hints
        _finish(session, entries)
        result.sessions.append(session)


def _append_to_last(
    sessions: list[SessionEntry], row: list[str], shape: TableShape
) -> None:
    _, topic, _, body = _row_cells(row, shape)
    tail = body if shape.from_header else " ".join(cell for cell in row if cell).strip()
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
