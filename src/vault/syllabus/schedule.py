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
    # an optional weekday in front, as in "Wednesday, August 19". without it
    # those lines fall through and end up listed as readings.
    r"^\s*(?:(?:mon|tues?|wed(?:nes)?|thur?s?|fri|sat(?:ur)?|sun)[a-z]*\.?,?\s+)?"
    r"(?P<date>(?:jan|feb|mar|apr|may|jun|jul|aug|sept?|oct|nov|dec)[a-z]*\.?,?"
    r"\s*\d{1,2}\s*(?:st|nd|rd|th)?)"
    # rest2 admits an opening quote before the capital: a survey course heads
    # its sessions "Mar 3 “The Victorian Age”...", and the curly quote was
    # failing the capital test. (?-i:) keeps the capital real under IGNORECASE.
    r"\s*(?:[:.–—-]\s*(?P<rest>.*)|\s+(?P<rest2>(?-i:[\"“]?[A-Z]).*)|(?P<rest3>)$)",
    re.IGNORECASE,
)


# a numbered meeting, as in "1. August 14: Introduction". the number belongs to
# the list, not to the date, so it is removed before matching. the space after
# the number is optional: tight kerning loses it, giving "1.August 14". a
# following capital is required, which keeps section numbers like "2.1" intact.
_MEETING_NUMBER_RE = re.compile(r"^\s*\(?\d{1,2}[.)]\s*(?=[A-Za-z])")


def strip_meeting_number(text: str) -> str:
    return _MEETING_NUMBER_RE.sub("", text, count=1)


# a line that opens with a numeric date, "8/18 Topic". used only to stamp an
# undated session from its own body, never to start a session: is_session_head
# firing on any line containing a fraction would shred schedules.
_NUMERIC_DATE_LEAD = re.compile(r"^\s*\d{1,2}\s*/\s*\d{1,2}\b")


# a numbered meeting that puts its date at the end instead of the front:
# "1. Introduction (01/13)". the number and the trailing date bracket the topic.
NUMBERED_DATED_RE = re.compile(
    r"^\s*\(?(?P<number>\d{1,2})[.)]\s*(?=[A-Za-z])(?P<topic>[^()]{2,90}?)\s*"
    r"\((?P<date>(?:\d{1,2}\s*/\s*\d{1,2}(?:\s*/\s*\d{2,4})?"
    r"|(?:jan|feb|mar|apr|may|jun|jul|aug|sept?|oct|nov|dec)[a-z]*\.?,?\s*\d{1,2}[^)]{0,12}))\)"
    r"\s*[:.]?\s*$",
    re.IGNORECASE,
)


def numbered_dated_heading(text: str) -> re.Match[str] | None:
    if len(text) > 140:
        return None
    return NUMBERED_DATED_RE.match(text)


def date_heading(text: str) -> re.Match[str] | None:
    """match a date-led session heading, if the line is one."""
    if len(text) > 160:
        return None
    return DATE_HEADING_RE.match(strip_meeting_number(text))


def is_session_head(text: str, *, starts_block: bool = True) -> bool:
    """a week marker anywhere, or a date heading that opens a block.

    a week marker is unambiguous. a date-led heading is not: prose inside a
    week can begin with a date too, so it only counts where a block starts,
    which is where a heading actually sits.
    """
    if WEEK_RE.match(text):
        return True
    if numbered_dated_heading(text):
        return True
    return starts_block and date_heading(text) is not None

# a keyword block label, as used by the labelled layout. the blocks that are
# not reading lists are named here too, so their content can be skipped rather
# than swept into whichever list was open above them.
LABEL_RE = re.compile(
    r"^\s*(?P<label>topic|readings?|review(?:\s*\([^)]*\))?|presentations?|due|"
    r"sign[\s-]?up|terms and key concepts|assignments?|watch|listen|optional|"
    r"recommended|required|"
    r"goals?|learning objectives?|objectives?|aims?|"
    r"discussion questions?|key concepts?|key terms?|terms|"
    r"in[\s-]class(?:\s+\w+)?|activit(?:y|ies)|notes?|reminders?)"
    r"\s*:\s*(?P<rest>.*)$",
    re.IGNORECASE,
)

# blocks whose content is never a reading
_SKIP_LABELS = re.compile(
    r"^(?:prose|goals?|learning objectives?|objectives?|aims?|discussion questions?|"
    r"key concepts?|key terms?|terms|terms and key concepts|"
    r"in[\s-]class|activit(?:y|ies)|notes?|reminders?)$",
    re.IGNORECASE,
)

# a label line that lost its colon in extraction, e.g. "Review (Inspectional
# Reading)" on its own line. without this it turns into a phantom reading.
BARE_LABEL_RE = re.compile(
    r"^\s*(?P<label>readings?|review(?:\s*\([^)]*\))?|terms and key concepts|"
    r"presentations?)\s*$",
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

# an asterisk in front of a line is a syllabus's own footnote mark. it says
# "look at this one", not "this is a reading", so it is stepped over before the
# line is read rather than being allowed to hide a "Due:" behind it.
DELIVERABLE_HINT_RE = re.compile(
    # a starred line that ends in the kind of work it is: "*Staff 1 & 2:
    # Significant Activity Report & Presentation", "*Staff Critical Mineral
    # Presentations". these are recurring assignments, and one seminar listed
    # four of them among its readings. the word has to close the line, or a
    # citation that merely mentions a report would be swallowed with it.
    r"^\s*\*.{0,60}\b(?:presentations?|reports?|memos?|briefs?|templates?)\b[\s.]*$|"
    r"^\s*\*?\s*(?:due|sign[\s-]?up|presentation|assessment|quiz|exam)\b|"
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
            if re.search(r"\bdates?\b.*\btopics?\b", flat):
                return True
    return False


# the same week marker as WEEK_RE, but usable mid string rather than anchored
_WEEK_ANYWHERE_RE = re.compile(
    r"\b(?:week|session|class|unit|module)\s*#?\s*\d{1,2}\b", re.IGNORECASE
)


def parse(doc: ExtractedDoc, zones: list[Zone], term: Term | None) -> ScheduleParse:
    """run the detected parser, and keep the best answer.

    detection reads the layout, but a syllabus can carry two schedules: a
    summary grid early and the real week by week listing later. picking one by
    shape alone then returns nothing while the other parser would have found
    fifteen weeks. so the runners up are tried whenever the winner comes back
    thin, and the fullest result wins. parsing is regex over lines already in
    memory, so the extra passes cost nothing worth counting.
    """
    lines = [line for z in zones if z.kind == SCHEDULE for line in z.lines]
    detected = detect_structure(doc, zones)

    def run(structure: str) -> ScheduleParse:
        if structure == TABLE:
            return _parse_table(doc, zones, term)
        if structure == LABELLED:
            return _parse_labelled(lines, term)
        return _parse_bulleted(lines, term)

    result = run(detected)
    for structure in (TABLE, LABELLED, BULLETED):
        if structure == detected:
            continue
        other = run(structure)
        # strictly better only, so detection wins every tie and stays the
        # default explanation for what happened
        if _score(other) > _score(result):
            result = other

    result.important_dates = _find_important_dates(doc, term)
    _demote_topic_outline(result)
    return result


# below this a schedule is too small to judge: two unrecognised lines really
# can be two hard readings, while forty of them are not a reading list.
_OUTLINE_MIN_ROWS = 4


def _demote_topic_outline(parsed: ScheduleParse) -> None:
    """a course outline is a list of topics, not a list of readings.

    plenty of syllabi head their outline "Module 1:" and bullet the sub topics
    under it. every bullet then looks exactly like a reading to the bulleted
    parser, and one course came back with fifty eight of them, none of which
    was anything to go and read. the same shape catches learning outcomes and
    the university welfare block where those land in the schedule zone.

    no single row can be judged: "The Australia Group" is a real assigned
    resource in one syllabus and a topic name in another. what separates them
    is the document. a real reading list resolves some of its citations; a
    topic outline resolves none of them, however long it runs. so the test is
    the whole schedule, not the line.

    the rows are not thrown away. a session with no topic takes its first row
    as one, which is what the line always was, and the rest are recorded as
    unparsed so review still shows them rather than the parser quietly
    deciding a page of the syllabus did not exist.
    """
    readings = [r for session in parsed.sessions for r in session.readings]
    if len(readings) < _OUTLINE_MIN_ROWS:
        return
    if any(r.citation.matched_pattern for r in readings):
        return

    for session in parsed.sessions:
        if not session.readings:
            continue
        if not session.topic:
            session.topic = collapse_whitespace(session.readings[0].raw)
            rest = session.readings[1:]
        else:
            rest = session.readings
        parsed.unparsed.extend(collapse_whitespace(r.raw) for r in rest)
        session.readings = []
        session.session_type = "topic"


def _score(parsed: ScheduleParse) -> tuple[int, int, int, int]:
    """rank one parse of a schedule against another.

    two signals, and neither works alone.

    dated meetings measure structure. running a flowing text parser over a
    table finds rows but no dates, because the dates were in a column it never
    saw, and a schedule with no dates is not a schedule.

    resolved citations measure content. a parse can date every meeting and
    still be the summary grid rather than the reading list, carrying three
    entries where the real listing has ninety.

    ranking on either one alone picks a known-wrong parse on real syllabi, so
    they are added. raw counts only break ties, and detection breaks the rest,
    which keeps the reported structure the honest explanation of the result.
    """
    dated = sum(1 for s in parsed.sessions if s.meeting_date)
    readings = [r for s in parsed.sessions for r in s.readings]
    resolved = sum(1 for r in readings if r.citation.matched_pattern)
    return dated + resolved, resolved, len(readings), len(parsed.sessions)


def _find_important_dates(doc: ExtractedDoc, term: Term | None) -> list[DatedEntry]:
    """read a standalone block of term dates wherever it appears."""
    for page in doc.pages:
        lines = page.text.splitlines()
        for index, line in enumerate(lines):
            # "notable dates" and "key dates" are the same block under a
            # different name, and one real file used each
            if re.match(r"^\s*(?:important|notable|key)\s+dates\s*:?\s*$", line, re.IGNORECASE):
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
    numbered = numbered_dated_heading(text)
    if numbered:
        session.week_number = int(numbered.group("number"))
        found = list(iter_dates(numbered.group("date"), term))
        if found:
            session.meeting_date = found[0]
        session.topic = collapse_whitespace(numbered.group("topic")).strip(" :,-–—") or None
        return

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


def _is_url_tail(text: str) -> bool:
    """is this entry nothing but a link.

    wrapping inside a table cell puts spaces in the middle of a url, so the
    words in one are no proof of prose. stripping every token that carries a
    slash or a dot leaves the words that were really text, and a web citation
    that kept its title still has some.
    """
    stripped = collapse_whitespace(text)
    if not stripped.lower().startswith(("http://", "https://", "www.")):
        return False
    remainder = re.sub(r"\S*[/.]\S*", " ", stripped)
    return len(remainder.split()) <= 1


# a token from the middle of a url path: lowercase, hyphenated, no prose
_PATH_TOKEN = re.compile(r"^[a-z0-9][a-z0-9\-_=&%.+/~]*$")


def _is_url_fragment(text: str) -> bool:
    """a url tail that lost its scheme when the cell wrapped."""
    tokens = collapse_whitespace(text).split()
    if not tokens or len(tokens) > 6:
        return False
    if not all(_PATH_TOKEN.match(token) for token in tokens):
        return False
    return sum(1 for t in tokens if "-" in t or "/" in t) >= max(1, len(tokens) - 1)


def _continues_url(previous: str, text: str) -> bool:
    """does this entry finish a url the one above it was cut off inside.

    the scheme is on the row above, so the tail on its own looks like nothing.
    both halves have to agree before they are joined: the row above has to
    carry a url and break off mid path, and this row has to be path and not
    prose. either test alone would swallow a page range.
    """
    prior = collapse_whitespace(previous).lower()
    if "http" not in prior and "www." not in prior:
        return False
    if not prior.endswith(("-", "/", "=", "_", "?", "&")):
        return False
    return _is_url_fragment(text)


def _join_url_tails(entries: list[str]) -> list[str]:
    """fold a link only entry into the one above it.

    a web citation is a title and a url together, and a cell that wraps can put
    the url on a row of its own. left alone it becomes a reading nobody can act
    on, and it also hides that the row above lost its link.
    """
    joined: list[str] = []
    for raw in entries:
        if joined and (_is_url_tail(raw) or _continues_url(joined[-1], raw)):
            joined[-1] = f"{joined[-1]} {collapse_whitespace(raw)}".strip()
            continue
        joined.append(raw)
    return joined


# the small words a title case heading is allowed to leave lowercase
_MINOR_WORDS = {"and", "of", "the", "for", "in", "to", "on", "with", "a", "an", "or"}


def _looks_like_reading_subheading(text: str) -> bool:
    """a thematic divider inside a reading list, not a reading.

    long reading lists get grouped under short headings ("Human Security",
    "Colonial Legacies"), and those were being checked off as though they were
    something to go and read. what marks them is the absence of everything a
    citation carries: no year, no page numbers, no quoted title, no link, no
    closing period, and few enough words to be a label.

    a standalone "in" is left out because it is how a chapter names the book it
    sits in, which is a real short form reading rather than a heading.
    """
    stripped = collapse_whitespace(text or "")
    if not stripped or len(stripped) > 46:
        return False
    tokens = stripped.split()
    if not tokens or len(tokens) > 6:
        return False
    if re.search(r"[\d\"“”]", stripped) or stripped.endswith("."):
        return False
    lowered = stripped.lower()
    if "http" in lowered or "www." in lowered or " in " in lowered:
        return False
    words = [w for w in tokens if w[:1].isalpha()]
    if len(words) < 2:
        return False
    return all(w[0].isupper() or w.lower() in _MINOR_WORDS for w in words)


def _lift_subheadings(session: SessionEntry, entries: list[str]) -> list[str]:
    """take dividers out of the reading list, keeping the first as a topic.

    a week that never named a topic often has one sitting right here, so the
    label is moved rather than thrown away.
    """
    kept: list[str] = []
    for raw in entries:
        if _looks_like_reading_subheading(raw):
            if not session.topic:
                session.topic = collapse_whitespace(raw)
            continue
        kept.append(raw)
    return kept


# a row that is nothing but requirement-level words is a sub-header from a
# two-column reading list ("Required   Suggested"), not a reading
_LEVEL_WORDS_ROW = re.compile(
    # the level word on its own, and the same word introducing the list it
    # heads: "Required Reading:", "Suggested Readings", "Optional Materials".
    # these are labels on a list, and each one was being checked off as a
    # thing to go and read.
    r"^\s*(?:required|suggested|optional|recommended|further|additional|core)"
    r"(?:\s+(?:required|suggested|optional|recommended))*"
    r"(?:\s+(?:reading|readings|material|materials|resource|resources|text|texts))?"
    r"\s*[:.]?\s*$",
    re.IGNORECASE,
)

# the same label arriving glued to the end of a real entry, because the next
# section's heading shared its line: "Text of the CWC: ... Suggested Reading:"
_TRAILING_LEVEL_LABEL_RE = re.compile(
    r"\s+(?:required|suggested|optional|recommended|further|additional)\s+"
    r"(?:reading|readings|material|materials|resource|resources)\s*:?\s*$",
    re.IGNORECASE,
)

# a required chapter cite fused with the suggested column beside it:
# "NRC Ch 3 & 4 Greenfire Movie". the chapter list is the split point, and
# both halves are real entries.
_CHAPTER_FUSE_RE = re.compile(
    r"^(?P<cite>[A-Z][\w'’-]*,?\s+(?:chapters?|ch\.?)\s*"
    r"[\d][\d]*(?:\s*[,&]\s*\d+)*)\s+(?P<rest>[A-Za-z]\S.*)$",
    re.IGNORECASE,
)


# a bullet in the middle of a line, with text on both sides. a reading list
# laid out in a narrow column often extracts as one long line carrying its
# whole week: "• RLMO, Ch. 2 • Seawright & Gerring (2008) • Mahoney (2012)".
# read as a single row it matches no citation pattern at all, so three real
# readings became one unparsed line. the marker must be a real bullet glyph;
# splitting on a hyphen or an asterisk would cut titles in half.
_INTERIOR_BULLET_RE = re.compile(r"\s+[•▪●◦‣⁃·]\s+")


def _split_bulleted_run(text: str) -> list[str]:
    """one line carrying several bulleted readings becomes several."""
    body = re.sub(r"^\s*[•▪●◦‣⁃·]\s*", "", text)
    parts = [p.strip() for p in _INTERIOR_BULLET_RE.split(body)]
    parts = [p for p in parts if len(p) >= 4]
    # two or more is a list; one means the line simply started with a bullet
    return parts if len(parts) >= 2 else []


def _split_fused_columns(entries: list[str]) -> list[tuple[str, str | None]]:
    """undo a required/suggested column merge, keeping the level of each half."""
    out: list[tuple[str, str | None]] = []
    for raw in entries:
        if _LEVEL_WORDS_ROW.match(collapse_whitespace(raw)):
            continue
        flat = collapse_whitespace(raw)
        pieces = _split_bulleted_run(flat)
        if pieces:
            out.extend((piece, None) for piece in pieces)
            continue
        m = _CHAPTER_FUSE_RE.match(flat)
        if m:
            out.append((m.group("cite"), None))
            out.append((m.group("rest"), "recommended"))
            continue
        out.append((raw, None))
    return out


def _finish(session: SessionEntry, entries: list[str]) -> None:
    ordinal = 0
    for raw, level in _split_fused_columns(
        _lift_subheadings(session, _join_url_tails(entries))
    ):
        entry = _build_reading(raw, ordinal)
        if entry is not None and level:
            entry.requirement_level = level
        if entry is None:
            continue
        session.readings.append(entry)
        ordinal += 1
    _classify_session(session)
    if session.readings:
        session.confidence = min(r.confidence for r in session.readings)


# a quoted span long enough to be a title. treating every quotation mark as a
# citation let whole paragraphs through, because prose scare-quotes a word or
# two all the time: various "crises", the EU's "State Secretary". a title runs
# longer than that.
_QUOTED_SPAN = re.compile(r"[\"“]([^\"”]{4,})[\"”]")


def _has_quoted_title(text: str) -> bool:
    return any(len(m.group(1).split()) >= 4 for m in _QUOTED_SPAN.finditer(text))


def _looks_like_prose(text: str) -> bool:
    """a week's description paragraph rather than a reading.

    plenty of syllabi write a few sentences under the week heading about what
    the week is for. that text sits exactly where a reading list sits and was
    being checked off as something to go and read.

    it is told apart by absence. a citation of any length carries a year, or a
    quoted title, or a page range, or a link, or it opens with a surname. a
    paragraph of English carries none of those, and runs long.
    """
    flat = collapse_whitespace(text)
    if len(flat.split()) < 22:
        return False
    if CITATION_START_RE.match(flat):
        return False
    if re.search(r"\b(?:19|20)\d{2}\b|https?://", flat) or _has_quoted_title(flat):
        return False
    # a page reference in any of the forms syllabi write it, spelled out
    # included. "Pages 29-37 in ..." is a reading, and only the page marker
    # says so.
    return not re.search(
        r"\bp(?:p|ages?|g)?\.?\s*\d|\bvol\.|\bno\.\s*\d|\bch(?:apter|\.)?\s*\d",
        flat,
        re.IGNORECASE,
    )


def _build_reading(raw: str, ordinal: int) -> ReadingEntry | None:
    text = collapse_whitespace(raw)
    if not text or len(text) < 4:
        return None
    if cit.looks_like_placeholder(text):
        return None
    # the next section's heading can share a line with the last entry of this
    # one, and it belongs to neither: strip it before anything else reads it
    text = _TRAILING_LEVEL_LABEL_RE.sub("", text).strip()
    if len(text) < 4:
        return None
    # a sub-header of level words from a two-column list reaches here by more
    # than one route, so the guard lives at the choke point
    if _LEVEL_WORDS_ROW.match(text):
        return None
    if _looks_like_prose(text):
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

    # "Chapter 2" or "pp. 12-30" is terse but it is a real assignment, and so
    # is "NRC Ch 3 & 4", where the chapter keyword sits after the set text's
    # acronym rather than first. anywhere in the text is enough: a url tail
    # does not carry "ch 3".
    if re.search(r"(?i)\b(?:chapters?|ch\.?|pages?|pp?\.?|parts?|sections?|units?)\s*\d", stripped):
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
    # a bulleted schedule still labels its blocks. "Learning objectives:" and
    # the bullets under it are not readings, and collecting them puts course
    # aims on the reading checklist.
    skipping = False

    def flush_entry() -> None:
        if current:
            buffer.append(" ".join(current))
            current.clear()

    def flush_session() -> None:
        nonlocal session, skipping
        flush_entry()
        if session is not None:
            _finish(session, buffer)
            result.sessions.append(session)
        buffer.clear()
        session = None
        skipping = False

    for line in lines:
        text = line.stripped
        if not text:
            continue

        stripped, marker = strip_leading_marker(text)
        heading_candidate = stripped if marker else text

        head = is_session_head(heading_candidate, starts_block=line.starts_block)
        # in a schedule that numbers its weeks, a bare date-led line is that
        # week's timetable or a stray from a summary grid, not a new session.
        # one syllabus's mangled summary calendar was donating a dozen
        # phantom sessions this way, one of them dating thanksgiving to
        # november 5th. week-numbered and numbered headings stay heads.
        if (head and not WEEK_RE.match(heading_candidate)
                and not numbered_dated_heading(heading_candidate)
                and any(s.week_number for s in result.sessions)):
            head = False

        if head:
            flush_session()
            session = _new_session(len(result.sessions), line.page, heading_candidate)
            session.section_heading = section_heading
            _split_week_heading(session, heading_candidate, term)
            continue

        if session is None:
            if _looks_like_unit_heading(text):
                section_heading = text.strip(" :")
            continue

        # a date led line sitting inside a week is that week's own timetable,
        # not a reading. it fails is_session_head because it is mid block rather
        # than at the top of one, and a week that lists "August 22 -Topic" under
        # its heading was otherwise putting each meeting on the reading list.
        # the pattern needs a bare month and day, so a citation carrying a full
        # date with a year does not reach here.
        meeting = date_heading(text)
        if meeting:
            flush_entry()
            found = list(iter_dates(text, term))
            if found and session.meeting_date is None:
                session.meeting_date = found[0]
            rest = collapse_whitespace(
                meeting.group("rest") or meeting.group("rest2") or ""
            )
            if rest and not session.topic:
                session.topic = rest
            continue

        # the numeric equivalent: "8/18 Topic" on the line under a bare
        # "Week 1" heading is that week's date. first date wins and only an
        # undated session takes it, so a citation carrying "12/3" mid-line or
        # a later assignment deadline cannot restamp the week.
        if session.meeting_date is None and _NUMERIC_DATE_LEAD.match(text):
            found = list(iter_dates(text, term))
            if found:
                session.meeting_date = found[0]

        # a label switches collection on or off for what follows it
        label = LABEL_RE.match(stripped) or BARE_LABEL_RE.match(stripped)
        if label:
            flush_entry()
            name = label.group("label").strip()
            skipping = _requirement_level(name) == "reference"
            rest = (label.groupdict().get("rest") or "").strip()
            if name.lower() == "topic":
                session.topic = collapse_whitespace(rest) or session.topic
                continue
            if not skipping and rest:
                current.append(rest)
            continue

        if skipping:
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
    section_heading: str | None = None

    # a syllabus that labels its reading blocks also writes a paragraph of
    # description under each week heading. treating what comes before the first
    # label as readings turns that prose into reading entries. so where labels
    # are in use, a block only becomes readings once a label says so; where
    # they are not, everything under the heading is the reading list.
    labels_in_use = sum(1 for line in lines if LABEL_RE.match(line.stripped)) >= 2
    opening_label = "prose" if labels_in_use else "readings"
    label = opening_label

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
        label = opening_label

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

        # a bare "Week 1" heading carries its date on the next line in some
        # tables: "T" then "8/18 Topic". first numeric date wins, undated
        # sessions only, same rule as the bulleted parser.
        if session.meeting_date is None and _NUMERIC_DATE_LEAD.match(text):
            found = list(iter_dates(text, term))
            if found:
                session.meeting_date = found[0]

        m = LABEL_RE.match(text) or BARE_LABEL_RE.match(text)
        if m:
            flush_entry()
            label = m.group("label").strip().lower()
            rest = (m.group("rest") or "").strip() if "rest" in m.groupdict() else ""
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

        # a terms list is a glossary: one line, one term. accumulating lines
        # the way citations need makes the count depend on where the page
        # breaks happened to fall, which is how the two extraction paths came
        # to disagree about the same syllabus.
        if label.startswith("terms"):
            flush_entry()
            current.append(text)
            flush_entry()
            continue

        if _starts_new_entry(text, current):
            flush_entry()
        current.append(text)

    flush_session()
    return result


def _finish_labelled(session: SessionEntry, tagged: list[tuple[str, str]]) -> None:
    ordinal = 0
    merged: list[tuple[str, str]] = []
    for label, raw in tagged:
        if merged and (_is_url_tail(raw) or _continues_url(merged[-1][1], raw)):
            previous_label, previous_raw = merged[-1]
            merged[-1] = (previous_label, f"{previous_raw} {collapse_whitespace(raw)}".strip())
            continue
        merged.append((label, raw))

    for label, raw in merged:
        if _looks_like_reading_subheading(raw):
            if not session.topic:
                session.topic = collapse_whitespace(raw)
            continue
        # graded work listed among the readings is a due date, not a reading.
        # the bulleted parser has always routed these to the deliverable hints;
        # a labelled block was still checking them off as things to read.
        flat = collapse_whitespace(raw)
        if DELIVERABLE_HINT_RE.match(flat):
            session.deliverable_hints.append(flat)
            continue
        # a terms and key concepts block is a glossary, not a reading list.
        # "De minimus calculations" is a thing to know, not a thing to read,
        # and listing it on a reading checklist makes the checklist useless.
        if _requirement_level(label) == "reference":
            continue
        # a labelled block gets the same treatment as a bulleted one: a line
        # carrying a whole week's readings between bullets is several rows
        for piece in _split_bulleted_run(flat) or [raw]:
            entry = _build_reading(piece, ordinal)
            if entry is None:
                continue
            entry.requirement_level = _requirement_level(label)
            session.readings.append(entry)
            ordinal += 1
    _classify_session(session)
    if session.readings:
        session.confidence = min(r.confidence for r in session.readings)


def _requirement_level(label: str) -> str:
    label = label.strip().lower()
    if _SKIP_LABELS.match(label):
        return "reference"
    if "inspectional" in label:
        return "inspectional"
    if label.startswith("review"):
        return "review"
    if label.startswith("recommend") or label.startswith("optional"):
        return "recommended"
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
    # a column the header calls "due" holds graded work, not readings. keeping
    # them apart stops "Participation 1" and "Syllabus Quiz Due" being listed
    # as things to read.
    due_cols: list[int] = field(default_factory=list)
    from_header: bool = False


# "week dates (days m-f)" is one syllabus's combined week-and-date column, so
# the week header tolerates a date qualifier; the promotion below then makes
# the same column the date anchor
_WEEK_HEADERS = re.compile(
    r"^\s*(?:week|wk|meetings?|class(?:es)?|session)s?\s*(?:dates?)?\s*(?:\([^)]*\))?\s*:?\s*$",
    re.IGNORECASE,
)
_DATE_HEADERS = re.compile(r"^\s*(?:date|dates|day|days)\b[^|]*$", re.IGNORECASE)
_TOPIC_HEADERS = re.compile(r"^\s*(?:topic|theme|subject)s?\s*:?\s*$", re.IGNORECASE)
_UNIT_HEADERS = re.compile(r"^\s*(?:unit|module|section|part)s?\s*:?\s*$", re.IGNORECASE)
_BODY_HEADERS = re.compile(
    r"^\s*(?:(?:assigned\s+)?readings?|materials?|notes?|"
    r"assignments?\s+and\s+due\s+dates?)\s*(?:\([^)]*\))?\s*:?\s*$",
    re.IGNORECASE,
)

# a column of graded work rather than a column of readings
# the last alternative reads any short header that ends in "due" as a due
# column: "Exams and Team Assignments due" names graded work however it winds
# up to the word. _label_kind checks body headers first, so "assignments and
# due dates" keeps its explicit body classification.
_DUE_HEADERS = re.compile(
    r"^\s*(?:assignments?|homework|deliverables?|(?:material|other|work)\s*due|"
    r"due(?:\s+dates?)?|what.?s\s+due|exams?|quizzes|"
    r"[\w\s/&@-]{0,36}\bdue)\s*(?:\([^)]*\))?\s*:?\s*$",
    re.IGNORECASE,
)


def _label_kind(label: str) -> str | None:
    """which column a header label names, if any."""
    if _WEEK_HEADERS.match(label):
        return "week"
    if _DATE_HEADERS.match(label):
        return "date"
    if _TOPIC_HEADERS.match(label):
        return "topic"
    if _UNIT_HEADERS.match(label):
        return "unit"
    if _BODY_HEADERS.match(label):
        return "body"
    if _DUE_HEADERS.match(label):
        return "due"
    return None


def _shape_from_header(grid: list[list[str]]) -> TableShape:
    shape = TableShape()
    if not grid:
        return shape

    kinds: list[str | None] = []
    for cell in grid[0]:
        first = collapse_whitespace(cell.split("\n")[0])
        kind = _label_kind(first)
        if kind is None:
            # a tall header cell wraps mid-phrase, so "Exams and\nTeam\n
            # Assignments due" shows a first line that names nothing. the
            # collapsed whole cell is the fallback, never the primary, so a
            # cell whose first line names a column keeps that reading.
            whole = collapse_whitespace(cell)
            if whole != first:
                kind = _label_kind(whole)
        kinds.append(kind)

    # a header physically split across two grid rows: the first row leaves a
    # column unnamed and the next row carries only its label ("", "", "Topic",
    # ""). merge those labels in, or the unnamed-column fallback later sweeps
    # the topic text into the readings. digits disqualify the row, so a short
    # data row cannot pass as a header continuation.
    if len(grid) > 1 and any(k is None for k in kinds):
        follow = [collapse_whitespace(c) for c in grid[1]]
        named = [(i, c) for i, c in enumerate(follow) if c]
        if named and all(_label_kind(c) and not re.search(r"\d", c) for _, c in named):
            for i, c in named:
                if i < len(kinds) and kinds[i] is None:
                    kinds[i] = _label_kind(c)

    recognised = 0
    for index, kind in enumerate(kinds):
        if kind == "week" and shape.week_col is None:
            shape.week_col, recognised = index, recognised + 1
        elif kind == "date":
            shape.date_cols.append(index)
            recognised += 1
        elif kind == "topic" and shape.topic_col is None:
            shape.topic_col, recognised = index, recognised + 1
        elif kind == "unit" and shape.unit_col is None:
            shape.unit_col, recognised = index, recognised + 1
        elif kind == "body":
            shape.body_cols.append(index)
            recognised += 1
        elif kind == "due":
            shape.due_cols.append(index)
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

    a column the header named is never read as something else. that separation
    is structural rather than a filter: a cell under "Topic" or under "Other
    Due" cannot leak into the readings no matter what it contains.

    the fallback below only sweeps up columns the header did not name at all,
    which is the case where guessing is the best available option. a grid whose
    header names its every column and none of them readings yields no readings,
    and that is the right answer rather than a gap to fill.
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
            named = anchor_cols | {shape.topic_col, shape.unit_col} | set(shape.due_cols)
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

    due_lines: list[str] = []
    if shape.from_header and shape.due_cols:
        for i in shape.due_cols:
            if i < len(row) and row[i].strip():
                due_lines.extend(
                    collapse_whitespace(part)
                    for part in row[i].splitlines()
                    if part.strip()
                )

    for index, (label, chunk) in enumerate(blocks):
        session = _new_session(len(result.sessions), page, f"{anchor} | {topic} | {chunk}".strip())
        session.week_number = week_number
        session.topic = collapse_whitespace(topic) or None
        session.section_heading = collapse_whitespace(unit) or None
        session.sub_session_label = label
        if dates:
            session.meeting_date = dates[min(index, len(dates) - 1)]
        entries, hints = _split_cell_entries(chunk)
        # a due column is graded work for this meeting, never a reading. it
        # belongs to the row, so it is attached once rather than to each
        # meeting the row covers.
        if due_lines and index == 0:
            hints = hints + due_lines
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
    ordinal = len(session.readings)
    for raw in entries:
        for piece in _split_bulleted_run(collapse_whitespace(raw)) or [raw]:
            entry = _build_reading(piece, ordinal)
            if entry is not None:
                session.readings.append(entry)
                ordinal += 1


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
