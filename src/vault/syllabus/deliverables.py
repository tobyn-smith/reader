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

# an assignment that states a per-item share and a total, or only a total:
# "Exams (15% each; 30% total)", "Diplomacy Lab (40% total, as divided below)".
# neither closes the bracket after the percentage, so the plain form above
# matched nothing at all and the assignment was dropped: one seminar's weights
# came to 60 because its exams and its papers both vanished. the total is the
# figure that belongs in the course, never the per-item share.
TOTAL_WEIGHT_RE = re.compile(
    r"(?P<title>[A-Z][\w&''’/,. ()-]{2,70}?)\s*\(\s*"
    r"(?:\d{1,3}(?:\.\d+)?\s*%\s*(?:each|apiece|per\s+\w+)\s*[;,]?\s*)?"
    r"(?P<weight>\d{1,3}(?:\.\d+)?)\s*%\s*total",
    re.IGNORECASE,
)
# a grading table row: a name, then a percentage, then maybe a date
TABLE_WEIGHT_RE = re.compile(
    r"^(?P<title>[A-Za-z][\w&''’/,. ()-]{2,70}?)\s{2,}(?P<weight>\d{1,3}(?:\.\d+)?)\s*%",
)

# a grading scale sits in the same column layout as the weights table, so its
# rows bleed into assignment titles: a stray "=F", a letter grade, or the tail
# of a score range like "87" left in front of the real title.
GRADE_LETTER_PREFIX_RE = re.compile(
    r"^(?:=?\s*[A-F][+-]?|\d{1,3}(?:\s*[-–]\s*\d{1,3})?)\s+(?=[A-Za-z])"
)
ORPHAN_WEIGHT_RE = re.compile(r"^\s*=?\s*(?P<weight>\d{1,3}(?:\.\d+)?)\s*%\s*$")

# the section heading printed in the first column of its own first row, as in
# "Grading Scheme:      Participation            50%". the row is a normal
# weights row wearing the heading, and anchored matching threw the whole line
# away. the gap after the colon is what says this is a column rather than a
# title that happens to end in one, so "Essay 1: 20%" is left alone.
INLINE_SECTION_LABEL_RE = re.compile(r"^(?P<label>[A-Za-z][A-Za-z ]{2,28}):\s{2,}(?=\S)")

# a whole line that is nothing but a name and a percentage: "Quizzes 30%".
# the columns of a grading table only survive as runs of spaces when the
# extractor happens to leave them, and one path collapses the very gaps the
# other keeps, so the same table scored 100 on the command line and nothing at
# all in the browser. anchoring both ends is what makes a single space safe
# here: prose does not end this way. the word cap keeps a sentence like "the
# final exam is worth 30%" from being read as a title.
LINE_WEIGHT_RE = re.compile(
    r"^\s*(?P<title>[A-Za-z][\w&'’/,.()+-]*(?:[ ][\w&'’/,.()+-]+){0,3})"
    r"\s+(?P<weight>\d{1,3}(?:\.\d+)?)\s*%\s*$"
)
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


SEE_SCHEDULE = "see schedule"


def extract(
    zones: list[Zone],
    term: Term | None,
    schedule_hints: list[tuple[str, dt.date | None]],
) -> DeliverableSet:
    """schedule_hints pairs each due or exam line with its session's date, so a
    cell reading only "EXAM 1 IN CLASS" still lands on the day it happens."""
    result = DeliverableSet()
    seen: dict[str, Deliverable] = {}

    for zone in zones:
        if zone.kind not in {REQUIREMENTS, FRONT_MATTER}:
            continue
        for item in _from_prose(zone, term):
            _merge(seen, item)
    _drop_recurrence_bleed(seen)

    for hint, session_date in schedule_hints:
        item = _from_hint(hint, term, session_date)
        if item is not None:
            _merge(seen, item)

    result.items = list(seen.values())
    _link_components_to_schedule(result.items)
    result.format_notes = _format_notes(zones)
    for item in result.items:
        if item.format_notes is None and result.format_notes:
            item.format_notes = result.format_notes[0]

    _check_weights(result)
    return result


def _link_components_to_schedule(items: list[Deliverable]) -> None:
    """connect an undated weight component to its dated occurrences.

    "Exams (3), 40%" in the grading summary and "EXAM 1 IN CLASS" on 9/16 in
    the schedule describe the same work. the component cannot carry three dates,
    but claiming the syllabus gives none is wrong, so it is marked as dated by
    the schedule instead.
    """
    dated_keys = [merge_key(i.title) for i in items if i.due_date]

    def stem(title: str) -> str:
        bare = merge_key(title).rstrip("s")
        return re.sub(r"\d+$", "", bare)

    for item in items:
        if item.due_date or item.recurrence or not item.weight_percent:
            continue
        item_stem = stem(item.title)
        if len(item_stem) < 4:
            continue
        if any(key.startswith(item_stem) and key != merge_key(item.title) for key in dated_keys):
            item.recurrence = SEE_SCHEDULE


@dataclass
class _Candidate:
    item: Deliverable
    marker: str
    # this row stated a total for itself, as in "(40% total, as divided
    # below)". only such a row is allowed to absorb the rows under it.
    declares_total: bool = False


def _from_prose(zone: Zone, term: Term | None) -> list[Deliverable]:
    candidates: list[_Candidate] = []

    # a grading table keeps its columns as runs of spaces, which collapsing a
    # paragraph destroys, so those rows are read from the untouched lines
    previous_title = ""
    previous_page = zone.start_page
    for line in zone.lines:
        raw = line.text.rstrip()
        # a heading sharing the first row of its own table is dropped, but only
        # when a real weights row is left behind once it goes
        label = INLINE_SECTION_LABEL_RE.match(raw)
        if label and TABLE_WEIGHT_RE.match(raw[label.end():]):
            raw = raw[label.end():]
        m = TABLE_WEIGHT_RE.match(raw) or LINE_WEIGHT_RE.match(raw)
        if m:
            title = _clean_title(m.group("title"))
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
        # the window is what follows the percentage. handing the whole row to
        # the builder lets a title like "Weekly Assessments" read as recurrence.
        tail = raw[m.end():] if m else ""
        item = _build(title, weight, tail, raw, zone.kind, page, term)
        candidates.append(_Candidate(item, "table"))

    for paragraph, page, markers in _paragraphs(zone):
        text = collapse_whitespace(paragraph)
        if not text:
            continue

        # a stated total wins over the bracketed share it sits beside, so the
        # totals are taken first and the plain form is only allowed where one
        # has not already claimed that stretch of the line
        totals = list(TOTAL_WEIGHT_RE.finditer(text))
        claimed = [(m.start(), m.end()) for m in totals]
        matches = totals + [
            m
            for m in TITLED_WEIGHT_RE.finditer(text)
            if not any(start < m.end() and m.start() < end for start, end in claimed)
        ]
        matches.sort(key=lambda m: m.start())
        # where each assignment's real name begins. the raw title group can
        # backtrack into the previous assignment's prose, so the boundary for
        # a body is the next tidied title, not the next raw match.
        starts: list[tuple[re.Match, str, int]] = []
        for m in matches:
            title = _tidy_title(m.group("title"))
            offset = m.group("title").rfind(title) if title else 0
            starts.append((m, title, m.start("title") + max(offset, 0)))

        for index, (m, title, _) in enumerate(starts):
            if len(title) < 3:
                continue
            stop = starts[index + 1][2] if index + 1 < len(starts) else len(text)
            body = text[m.end(): min(stop, m.end() + 900)]
            item = _build(title, float(m.group("weight")), body, text, zone.kind, page, term)
            candidates.append(_Candidate(
                item,
                _marker_for(m.start(), text, markers),
                declares_total=m.re is TOTAL_WEIGHT_RE,
            ))

        extra = EXTRA_CREDIT_RE.search(text)
        if extra:
            item = _build(
                collapse_whitespace(extra.group("title")).strip(" .,:-") or "extra credit",
                float(extra.group("weight")),
                # only what follows the mention, or a "weekly" elsewhere in the
                # paragraph becomes this item's recurrence
                text[extra.end(): extra.end() + 300],
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


# grading apparatus that carries a percentage without being an assignment:
# the summary row that adds the table up, and a late-penalty scale whose rows
# read "Late within two days ... 40%". both were counted as graded work on a
# real syllabus and pushed the weight total to 500.
_APPARATUS_RE = re.compile(
    r"^\s*(?:total|totals?|sum|on[\s-]?time|late\s+(?:within|after|by)\b|"
    r"(?:\d+\s*)?days?\s+late|"
    # the heading of the grading section itself, picked up with the 100 beside
    # it and reported as an assignment worth the whole course
    r"grading\s+(?:polic|scale|criteria|rubric|breakdown|summar))",
    re.IGNORECASE,
)


def _absorb_subdivisions(candidates: list[_Candidate]) -> list[_Candidate]:
    """drop the parts of an assignment that stated its own total.

    "Diplomacy Lab (40% total, as divided below)" is followed by the four
    pieces it divides into, ten per cent each. counting the parent and its
    parts both put that course at a hundred and forty.

    only a row that declared a total may absorb anything, which is what keeps
    three ordinary assignments that happen to add up to a fourth from
    swallowing each other.
    """
    keep = [True] * len(candidates)
    for index, parent in enumerate(candidates):
        weight = parent.item.weight_percent
        if not parent.declares_total or not weight or not keep[index]:
            continue
        running = 0.0
        for end in range(index + 1, len(candidates)):
            child = candidates[end].item.weight_percent
            if not keep[end] or not child or candidates[end].declares_total:
                break
            running += child
            if running > weight + 0.5:
                break
            # at least two parts, or it is a restatement rather than a division
            if abs(running - weight) <= 0.5 and end > index + 1:
                for position in range(index + 1, end + 1):
                    keep[position] = False
                break
    return [c for c, k in zip(candidates, keep) if k]


def _select_top_level(candidates: list[_Candidate]) -> list[Deliverable]:
    """drop the sub components of a multi part assignment.

    an assignment broken into graded parts lists those parts at a deeper bullet
    level, and their weights are a breakdown of the parent rather than extra
    weight. when one bullet level accounts for the whole grade on its own, that
    level is the real list of deliverables.
    """
    candidates = [c for c in candidates if not _APPARATUS_RE.match(c.item.title)]
    candidates = _absorb_subdivisions(candidates)
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
    elif len(collapse_whitespace(window)) < 40:
        # a grading table writes "20%  February 2nd" with no keyword at all.
        # in a window that short, a date is the due date.
        dates = list(iter_dates(window, term))
        if dates:
            item.due_date = dates[0]

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


def _from_hint(
    hint: str, term: Term | None, session_date: dt.date | None = None
) -> Deliverable | None:
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
    elif session_date is not None:
        # the cell names the event and the row carries the date
        item.due_date = session_date
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


def _clean_title(raw: str) -> str:
    title = collapse_whitespace(raw).strip(" .,:-")
    return GRADE_LETTER_PREFIX_RE.sub("", title).strip()


def _significant_words(title: str) -> set[str]:
    bare = re.sub(r"\([^)]*\)", " ", title.lower())
    words = re.findall(r"[a-z]{3,}", bare)
    return {w for w in words if w not in _TITLE_STOP}


_TITLE_STOP = {
    "and", "the", "for", "with", "from", "into", "your", "our", "its",
    "report", "reports", "paper", "papers", "assignment", "assignments",
    "presentation", "presentations", "project", "projects", "study", "studies",
    # the kind of thing it is says nothing about which one it is. a midterm and
    # a final are both exams, often for the same weight, and merging them loses
    # a whole assignment from the total.
    "exam", "exams", "quiz", "quizzes", "test", "tests", "essay", "essays",
    "memo", "memos", "response", "responses",
}


def _same_assignment(a: Deliverable, b: Deliverable) -> bool:
    """decide whether two rows describe one piece of work.

    a grade summary and the paragraph that explains the same assignment rarely
    use the same words: one says "MECR and International Assistance Reports"
    and the other "Export Control Regime (MECR) and International Assistance".
    matching on the exact string leaves both rows in place and the weights then
    add up to well over a hundred, which is how this shows up.

    an identical stated weight plus real overlap in the distinctive words is
    strong evidence, because one course almost never has two different
    assignments worth exactly the same amount and named almost the same.
    """
    if a.weight_percent is None or a.weight_percent != b.weight_percent:
        return False
    left, right = _significant_words(a.title), _significant_words(b.title)
    if not left or not right:
        return False
    shared = left & right
    # two shared words at minimum. one word in common is how "Midterm Exam" and
    # "Final Exam", both worth thirty, ended up as a single row.
    if len(shared) < 2 and shared != left and shared != right:
        return False
    if len(shared) / min(len(left), len(right)) < 0.6:
        return False

    # when a title carries only one distinctive word, the stop list has taken
    # the word that told the two apart: "Policy Memos" and "Policy Report" both
    # come down to "policy", match on it, and one of them, thirty per cent of
    # the course, disappears. the full titles get the casting vote.
    if min(len(left), len(right)) < 2:
        whole_left, whole_right = _title_words(a.title), _title_words(b.title)
        if not whole_left or not whole_right:
            return False
        overlap = whole_left & whole_right
        return len(overlap) / min(len(whole_left), len(whole_right)) >= 0.6
    return True


def _title_words(title: str) -> set[str]:
    """every word of a title, stop list and all."""
    bare = re.sub(r"\([^)]*\)", " ", title.lower())
    return {w for w in re.findall(r"[a-z]{3,}", bare) if w not in {"and", "the", "for"}}


def _merge(seen: dict[str, Deliverable], item: Deliverable) -> None:
    """same assignment described twice keeps the more complete description."""
    key = merge_key(item.title)
    if not key:
        return
    existing = seen.get(key)
    if existing is not None:
        _fill_missing(existing, item)
        return

    for other in seen.values():
        if _same_assignment(other, item):
            _fill_missing(other, item)
            # keep whichever title reads better: the longer one usually carries
            # the qualifier that makes it findable
            if len(item.title) > len(other.title):
                other.title = item.title
            return

    seen[key] = item


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


_BONUS_TITLE_RE = re.compile(r"\b(?:extra\s+credit|bonus)\b", re.IGNORECASE)


def _check_weights(result: DeliverableSet) -> None:
    """weights should land near 100. a miss is reported, never silently fixed."""
    # extra credit sits on top of the hundred rather than inside it, so adding
    # it in reported a course whose weights were exactly right as five over.
    # the item keeps its weight; it just does not count towards the total.
    weights = [i.weight_percent for i in result.items
               if i.weight_percent and not _BONUS_TITLE_RE.search(i.title or "")]
    total = round(sum(weights), 2)
    result.weight_total = total
    # these are read by a student, not by whoever wrote the parser. say what
    # was found, what it probably means, and where to look. a total that is
    # wrong is never quietly corrected.
    if not weights:
        result.weight_warning = (
            "No percentages found for the graded work. Check the grading "
            "section of your syllabus."
        )
        return
    if 99.0 <= total <= 100.5:
        return
    if 100.5 < total <= 110.0:
        result.weight_warning = (
            f"The graded work adds up to {total}%. A little over 100 is normal "
            "when there is extra credit."
        )
        return
    if total < 99.0:
        result.weight_warning = (
            f"Only {total}% of your grade was found, so some assignments are "
            "probably missing. Check the grading section of your syllabus."
        )
        return
    result.weight_warning = (
        f"The graded work adds up to {total}%, which is more than 100. "
        "Something may have been counted twice."
    )
