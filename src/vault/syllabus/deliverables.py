"""graded work, which is mostly defined in prose rather than in the schedule.

a syllabus usually names its assignments in a paragraph pages before the week by
week plan, states the weight there, and then mentions the date somewhere else
again. so both zones are read and the results reconciled by title.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field

from ..text.normalize import collapse_whitespace, strip_leading_marker
from .dates import Term, iter_dates, parse_time, parse_weekday
from .zones import FRONT_MATTER, REQUIREMENTS, SCHEDULE, Zone

WEEKDAY_NAMES = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "fifteen": 15,
    "twenty": 20, "twenty-five": 25, "thirty": 30, "forty": 40, "fifty": 50,
}


@dataclass
class Deliverable:
    title: str
    kind: str = "other"
    due_date: dt.date | None = None
    due_time: dt.time | None = None
    recurrence: str | None = None
    weight_percent: float | None = None
    page_limit: int | None = None
    word_limit: int | None = None
    format_notes: str | None = None
    requirements_text: str = ""
    source_zone: str = REQUIREMENTS
    page_number: int = 0
    confidence: float = 0.8


@dataclass
class DeliverableSet:
    items: list[Deliverable] = field(default_factory=list)
    weight_total: float = 0.0
    weight_warning: str | None = None
    format_notes: list[str] = field(default_factory=list)


# "Mid-term Essay (20%):" or "Reading Checklist & Class Participation (30%)"
TITLED_WEIGHT_RE = re.compile(
    r"(?P<title>[A-Z][\w&''’/,. ()-]{2,70}?)\s*\(\s*(?P<weight>\d{1,3}(?:\.\d+)?)\s*%\s*\)",
)
# a grading table row: a name, then a percentage, then maybe a date
TABLE_WEIGHT_RE = re.compile(
    r"^(?P<title>[A-Za-z][\w&''’/,. ()-]{2,70}?)\s{2,}(?P<weight>\d{1,3}(?:\.\d+)?)\s*%",
)
ORPHAN_WEIGHT_RE = re.compile(r"^\s*=?\s*(?P<weight>\d{1,3}(?:\.\d+)?)\s*%\s*$")
EXTRA_CREDIT_RE = re.compile(
    r"(?P<title>[\w ]*extra credit[\w ]*)\s*\+?\s*(?P<weight>\d{1,3})\s*%", re.IGNORECASE
)

PAGE_LIMIT_RE = re.compile(
    r"\b(?:maximum|max\.?|no more than|up to|limit(?:ed)? to|not exceed)\s+"
    r"(?P<count>\d{1,3}|" + "|".join(NUMBER_WORDS) + r")\s*(?:double[- ]spaced\s+)?pages?\b",
    re.IGNORECASE,
)
PAGE_RANGE_LIMIT_RE = re.compile(r"\b(?P<low>\d{1,3})\s*[-–—]\s*(?P<high>\d{1,3})\s*page\b", re.IGNORECASE)
WORD_LIMIT_RE = re.compile(
    r"\b(?:maximum|max\.?|no more than|up to|about|approximately)\s+"
    r"(?P<count>[\d,]{3,7})\s*words?\b",
    re.IGNORECASE,
)

RECURRING_RE = re.compile(
    r"\b(each week|every week|weekly|each class|before (?:each|every) class)\b", re.IGNORECASE
)
DUE_RE = re.compile(r"\b(?:due|submit(?:ted)?|turn(?:ed)? in)\b", re.IGNORECASE)

FORMAT_RE = re.compile(
    r"([^.]*\b(?:times new roman|font|double[- ]spaced|point|pt\b|citation style|"
    r"memo format|hard copy|via email|file name)\b[^.]*\.)",
    re.IGNORECASE,
)

_KIND_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("exam", re.compile(r"\b(exam|midterm|final|test|quiz)\b", re.IGNORECASE)),
    ("weekly_assessment", re.compile(r"\b(weekly assessment|assessment \d+)\b", re.IGNORECASE)),
    ("checklist", re.compile(r"\bchecklist\b", re.IGNORECASE)),
    ("proposal", re.compile(r"\b(proposal|pre[- ]?registration|prospectus)\b", re.IGNORECASE)),
    ("presentation", re.compile(r"\b(presentation|present\b)", re.IGNORECASE)),
    ("case_study", re.compile(r"\bcase stud(?:y|ies)\b", re.IGNORECASE)),
    ("signup", re.compile(r"\bsign[\s-]?up\b", re.IGNORECASE)),
    ("essay", re.compile(r"\b(essay|paper|memo)\b", re.IGNORECASE)),
    ("report", re.compile(r"\breports?\b", re.IGNORECASE)),
]


def classify_kind(title: str, body: str = "") -> str:
    probe = f"{title} {body[:200]}"
    for kind, pattern in _KIND_PATTERNS:
        if pattern.search(probe):
            return kind
    return "other"


def _to_int(raw: str) -> int | None:
    raw = raw.strip().lower().replace(",", "")
    if raw.isdigit():
        return int(raw)
    return NUMBER_WORDS.get(raw)


def extract(zones: list[Zone], term: Term | None, schedule_hints: list[str]) -> DeliverableSet:
    result = DeliverableSet()
    seen: dict[str, Deliverable] = {}

    for zone in zones:
        if zone.kind not in {REQUIREMENTS, FRONT_MATTER}:
            continue
        for item in _from_prose(zone, term):
            _merge(seen, item)
    _drop_recurrence_bleed(seen)

    for hint in schedule_hints:
        item = _from_hint(hint, term)
        if item is not None:
            _merge(seen, item)

    result.items = list(seen.values())
    result.format_notes = _format_notes(zones)
    for item in result.items:
        if item.format_notes is None and result.format_notes:
            item.format_notes = result.format_notes[0]

    _check_weights(result)
    return result


@dataclass
class _Candidate:
    item: Deliverable
    marker: str


def _from_prose(zone: Zone, term: Term | None) -> list[Deliverable]:
    candidates: list[_Candidate] = []

    # a grading table keeps its columns as runs of spaces, which collapsing a
    # paragraph destroys, so those rows are read from the untouched lines
    previous_title = ""
    previous_page = zone.start_page
    for line in zone.lines:
        raw = line.text.rstrip()
        m = TABLE_WEIGHT_RE.match(raw)
        if m:
            title = collapse_whitespace(m.group("title")).strip(" .,:-")
            weight = float(m.group("weight"))
            page = line.page
        elif ORPHAN_WEIGHT_RE.match(raw) and previous_title:
            # the column split across lines, leaving the percentage on its own
            title = previous_title
            weight = float(ORPHAN_WEIGHT_RE.match(raw).group("weight"))
            page = previous_page
            previous_title = ""
        else:
            if raw.strip() and not raw.strip().endswith("%"):
                candidate_title = collapse_whitespace(raw).strip(" .,:-")
                if 3 <= len(candidate_title) <= 60:
                    previous_title, previous_page = candidate_title, line.page
            continue

        if len(title) < 3:
            continue
        item = _build(title, weight, raw, raw, zone.kind, page, term)
        candidates.append(_Candidate(item, "table"))

    for paragraph, page, markers in _paragraphs(zone):
        text = collapse_whitespace(paragraph)
        if not text:
            continue

        matches = list(TITLED_WEIGHT_RE.finditer(text))
        for index, m in enumerate(matches):
            title = _tidy_title(m.group("title"))
            if len(title) < 3:
                continue
            # the description of an assignment stops where the next one starts,
            # otherwise a due date bleeds onto the assignment above it
            stop = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            body = text[m.end(): min(stop, m.end() + 900)]
            item = _build(title, float(m.group("weight")), body, text, zone.kind, page, term)
            candidates.append(_Candidate(item, _marker_for(m.start(), text, markers)))

        extra = EXTRA_CREDIT_RE.search(text)
        if extra:
            item = _build(
                collapse_whitespace(extra.group("title")).strip(" .,:-") or "extra credit",
                float(extra.group("weight")),
                text,
                text,
                zone.kind,
                page,
                term,
            )
            candidates.append(_Candidate(item, "extra"))

    return _select_top_level(candidates)


def _tidy_title(raw: str) -> str:
    """keep only the last sentence fragment before the weight.

    once lines are joined, the pattern can start matching in the tail of the
    previous sentence, which produces titles like "may result in a grade
    reduction. Week 5 Assignment". the real title is what follows the last
    sentence break.
    """
    title = collapse_whitespace(raw)
    if ". " in title:
        title = title.rsplit(". ", 1)[1]
    return title.strip(" .,:-")


def _marker_for(position: int, text: str, markers: list[tuple[int, str]]) -> str:
    """which list marker the assignment at this position sits under."""
    current = ""
    for offset, marker in markers:
        if offset <= position:
            current = marker
        else:
            break
    return current


def _select_top_level(candidates: list[_Candidate]) -> list[Deliverable]:
    """drop the sub components of a multi part assignment.

    an assignment broken into graded parts lists those parts at a deeper bullet
    level, and their weights are a breakdown of the parent rather than extra
    weight. when one bullet level accounts for the whole grade on its own, that
    level is the real list of deliverables.
    """
    if not candidates:
        return []

    # collapse repeat descriptions before grouping, otherwise a level that
    # really does add up to 100 looks like it adds up to 135. the grading
    # summary line names an assignment first and the detailed paragraph
    # describes it properly later, so duplicates are merged rather than
    # dropped, or the due dates and page limits would be lost with them.
    unique: list[_Candidate] = []
    by_key: dict[str, _Candidate] = {}
    for candidate in candidates:
        key = merge_key(candidate.item.title)
        kept = by_key.get(key)
        if key and kept is not None:
            _fill_missing(kept.item, candidate.item)
            continue
        by_key[key] = candidate
        unique.append(candidate)
    candidates = unique

    groups: dict[str, list[_Candidate]] = {}
    for candidate in candidates:
        groups.setdefault(candidate.marker, []).append(candidate)

    if len(groups) > 1:
        for marker, members in groups.items():
            total = sum(c.item.weight_percent or 0 for c in members)
            if 99.0 <= total <= 100.5 and len(members) > 1:
                extras = [c for c in candidates if c.marker == "extra"]
                return [c.item for c in members + extras]

    return [c.item for c in candidates]


def _build(
    title: str,
    weight: float | None,
    body: str,
    full: str,
    zone_kind: str,
    page: int,
    term: Term | None,
) -> Deliverable:
    item = Deliverable(
        title=title,
        kind=classify_kind(title, body),
        weight_percent=weight,
        # the verbatim prose for this assignment alone. storing the whole
        # paragraph looks harmless but a page that extracts as one block would
        # attach the entire page to every assignment on it.
        requirements_text=collapse_whitespace(f"{title}: {body}" if body else full)[:2000],
        source_zone=zone_kind,
        page_number=page,
    )

    window = body
    if DUE_RE.search(window):
        dates = list(iter_dates(window, term))
        if dates:
            item.due_date = dates[0]
        item.due_time = parse_time(window)

    if RECURRING_RE.search(window):
        weekday = parse_weekday(window)
        day = WEEKDAY_NAMES[weekday] if weekday is not None else None
        item.recurrence = f"weekly on {day}" if day else "weekly"
        item.due_date = None

    m = PAGE_LIMIT_RE.search(window)
    if m:
        item.page_limit = _to_int(m.group("count"))
    else:
        m = PAGE_RANGE_LIMIT_RE.search(window)
        if m:
            item.page_limit = _to_int(m.group("high"))

    m = WORD_LIMIT_RE.search(window)
    if m:
        item.word_limit = _to_int(m.group("count"))

    filled = sum(
        1 for value in (item.weight_percent, item.due_date or item.recurrence, item.page_limit)
        if value
    )
    item.confidence = round(0.5 + 0.15 * filled, 3)
    return item


def _from_hint(hint: str, term: Term | None) -> Deliverable | None:
    """turn a due or sign-up line found inside the schedule into a row."""
    text = collapse_whitespace(hint)
    if len(text) < 5:
        return None

    # only a label colon splits the line. a colon inside a clock time does not,
    # or "assessment due at 11:59 pm" becomes an assignment called "59 pm".
    m = re.match(r"^\s*(?P<label>[A-Za-z][\w\s-]{1,24}?)\s*:\s*(?P<rest>\S.*)$", text)
    title = collapse_whitespace(m.group("rest") if m else text).strip(" .,-")
    # the date tail is data, not name: "Assessment 4 due 9/21 at 11:59 pm" is
    # the assignment "Assessment 4"
    title = re.split(r"\s+due\s+", title, maxsplit=1, flags=re.IGNORECASE)[0].strip(" .,-")
    if not title:
        return None

    item = Deliverable(
        title=title[:120],
        kind=classify_kind(title, text),
        requirements_text=text,
        source_zone=SCHEDULE,
        confidence=0.6,
    )
    dates = list(iter_dates(text, term))
    if dates:
        item.due_date = dates[0]
    item.due_time = parse_time(text)
    if re.match(r"^\s*sign[\s-]?up", text, re.IGNORECASE):
        item.kind = "signup"
    return item


def merge_key(title: str) -> str:
    """identity of an assignment, ignoring how it was qualified.

    the same assignment is routinely named twice, once in the grade summary and
    once in its own paragraph, with a parenthetical that differs between them.
    those have to collapse to one row or the weights double count.
    """
    bare = re.sub(r"\([^)]*\)", " ", title.lower())
    return re.sub(r"[^a-z0-9]+", "", bare)[:40]


def _fill_missing(target: Deliverable, source: Deliverable) -> None:
    for attribute in (
        "due_date", "due_time", "recurrence", "weight_percent",
        "page_limit", "word_limit", "format_notes",
    ):
        if getattr(target, attribute) is None:
            setattr(target, attribute, getattr(source, attribute))
    if len(source.requirements_text) > len(target.requirements_text):
        target.requirements_text = source.requirements_text
    if source.kind != "other" and target.kind == "other":
        target.kind = source.kind
    target.confidence = max(target.confidence, source.confidence)


def _merge(seen: dict[str, Deliverable], item: Deliverable) -> None:
    """same assignment described twice keeps the more complete description."""
    key = merge_key(item.title)
    if not key:
        return
    existing = seen.get(key)
    if existing is None:
        seen[key] = item
        return
    _fill_missing(existing, item)


def _drop_recurrence_bleed(seen: dict[str, Deliverable]) -> None:
    """a recurring assignment does not make its neighbours recurring.

    only keep a weekly marking where the assignment's own description says so,
    which is checked against its recorded prose rather than the paragraph it
    happened to share.
    """
    for item in seen.values():
        if item.recurrence and not RECURRING_RE.search(item.requirements_text[:400]):
            item.recurrence = None


def _paragraphs(zone: Zone):
    """yield paragraph text, its page, and where each list marker fell in it.

    the marker offsets are what let nested sub components be told apart from top
    level assignments once the lines have been joined into one string.
    """
    buffer: list[str] = []
    markers: list[tuple[int, str]] = []
    page = zone.start_page
    length = 0

    def emit():
        return " ".join(buffer), page, list(markers)

    for line in zone.lines:
        if not line.stripped:
            if buffer:
                yield emit()
                buffer, markers, length = [], [], 0
            continue
        if not buffer:
            page = line.page
        stripped, marker = strip_leading_marker(line.stripped)
        if marker:
            markers.append((length, marker))
        buffer.append(stripped if marker else line.stripped)
        length += len(buffer[-1]) + 1

    if buffer:
        yield emit()


def _format_notes(zones: list[Zone]) -> list[str]:
    notes: list[str] = []
    for zone in zones:
        if zone.kind not in {REQUIREMENTS, FRONT_MATTER}:
            continue
        for m in FORMAT_RE.finditer(zone.text):
            note = collapse_whitespace(m.group(1))
            if 20 < len(note) < 400 and note not in notes:
                notes.append(note)
    return notes


def _check_weights(result: DeliverableSet) -> None:
    """weights should land near 100. a miss is reported, never silently fixed."""
    weights = [i.weight_percent for i in result.items if i.weight_percent]
    total = round(sum(weights), 2)
    result.weight_total = total
    if not weights:
        result.weight_warning = "no assignment weights found"
        return
    if 99.0 <= total <= 100.5:
        return
    if 100.5 < total <= 110.0:
        result.weight_warning = (
            f"weights total {total}%, slightly over 100, which is normal when extra credit is offered"
        )
        return
    result.weight_warning = f"weights total {total}%, which does not add up to 100"
