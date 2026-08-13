"""term inference and the date formats that turn up in schedules.

syllabus dates are almost never fully qualified. a schedule says "8/21" or
"January 27th" and expects the reader to know the year from the cover page, so
the term has to be resolved first and then applied.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass

MONTHS = {
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3,
    "april": 4, "apr": 4, "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7,
    "august": 8, "aug": 8, "september": 9, "sep": 9, "sept": 9, "october": 10,
    "oct": 10, "november": 11, "nov": 11, "december": 12, "dec": 12,
}

# which calendar months a term covers, used to decide the year for a bare month
TERM_MONTHS = {
    "fall": {8, 9, 10, 11, 12},
    "spring": {1, 2, 3, 4, 5},
    "summer": {5, 6, 7, 8},
    "winter": {12, 1, 2},
}

_TERM_RE = re.compile(
    # a season joined to another by a slash or dash is a journal issue, not a
    # course term: "Spring/Summer 2016" in a reading list made a 2026 syllabus
    # report itself as ten years old. the lookbehind refuses that shape.
    r"(?<![/–—-])\b(fall|spring|summer|winter)\s+(20\d{2})\b"
    r"|\b(20\d{2})\s+(fall|spring|summer|winter)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Term:
    name: str
    year: int

    def __str__(self) -> str:
        return f"{self.name.title()} {self.year}"

    def year_for_month(self, month: int) -> int:
        """a winter term straddles new year, so january belongs to year + 1."""
        if self.name == "winter" and month <= 2:
            return self.year + 1
        return self.year


def find_term(text: str) -> Term | None:
    m = _TERM_RE.search(text)
    if not m:
        return None
    if m.group(1):
        return Term(m.group(1).lower(), int(m.group(2)))
    return Term(m.group(4).lower(), int(m.group(3)))


# the separator between month and day varies more than it should: a space, no
# space at all in kerning-heavy pdfs ("Aug13-15"), a period after an
# abbreviation, or a comma ("February, 5"). the lookahead stops a year being
# read as a day, so "August 2020" is not august 20.
_ORDINAL_RE = re.compile(
    r"\b(" + "|".join(MONTHS) + r")\.?,?\s*(\d{1,2})(?!\d)\s*(?:st|nd|rd|th)?\b",
    re.IGNORECASE,
)
_NUMERIC_RE = re.compile(r"\b(\d{1,2})\s*/\s*(\d{1,2})(?:\s*/\s*(\d{2,4}))?\b")


def parse_date(fragment: str, term: Term | None) -> dt.date | None:
    """read the first date in a fragment, using the term to supply the year."""
    for candidate in iter_dates(fragment, term):
        return candidate
    return None


def iter_dates(fragment: str, term: Term | None):
    """yield every date in a fragment in the order it appears.

    a table cell for a course that meets twice a week holds two dates, and both
    matter, so callers need all of them rather than just the first.
    """
    seen: list[tuple[int, dt.date]] = []

    for m in _ORDINAL_RE.finditer(fragment):
        month = MONTHS[m.group(1).lower()]
        day = int(m.group(2))
        built = _build(month, day, term)
        if built:
            seen.append((m.start(), built))

    for m in _NUMERIC_RE.finditer(fragment):
        month, day = int(m.group(1)), int(m.group(2))
        if m.group(3):
            year = int(m.group(3))
            year += 2000 if year < 100 else 0
            built = _safe_date(year, month, day)
        else:
            built = _build(month, day, term)
        if built:
            seen.append((m.start(), built))

    for _, value in sorted(seen, key=lambda pair: pair[0]):
        yield value


def _build(month: int, day: int, term: Term | None) -> dt.date | None:
    if term is None:
        return None
    return _safe_date(term.year_for_month(month), month, day)


def _safe_date(year: int, month: int, day: int) -> dt.date | None:
    try:
        return dt.date(year, month, day)
    except ValueError:
        return None


_TIME_RE = re.compile(
    r"\b(\d{1,2})[:.](\d{2})\s*([ap])\.?\s*m\.?|\b(\d{1,2})\s*([ap])\.?\s*m\.?\b",
    re.IGNORECASE,
)


def parse_time(fragment: str) -> dt.time | None:
    """read a due time. "midnight" is treated as the end of the stated day."""
    if re.search(r"\bmidnight\b", fragment, re.IGNORECASE):
        return dt.time(23, 59)
    if re.search(r"\bnoon\b", fragment, re.IGNORECASE):
        return dt.time(12, 0)

    m = _TIME_RE.search(fragment)
    if not m:
        return None
    if m.group(1):
        hour, minute, meridiem = int(m.group(1)), int(m.group(2)), m.group(3).lower()
    else:
        hour, minute, meridiem = int(m.group(4)), 0, m.group(5).lower()
    if hour == 12:
        hour = 0
    if meridiem == "p":
        hour += 12
    return _safe_time(hour, minute)


def _safe_time(hour: int, minute: int) -> dt.time | None:
    try:
        return dt.time(hour, minute)
    except ValueError:
        return None


WEEKDAYS = {
    "monday": 0, "mon": 0, "tuesday": 1, "tue": 1, "tues": 1, "wednesday": 2,
    "wed": 2, "thursday": 3, "thu": 3, "thur": 3, "thurs": 3, "friday": 4,
    "fri": 4, "saturday": 5, "sat": 5, "sunday": 6, "sun": 6,
}
_WEEKDAY_RE = re.compile(r"\b(" + "|".join(WEEKDAYS) + r")s?\b", re.IGNORECASE)


def parse_weekday(fragment: str) -> int | None:
    m = _WEEKDAY_RE.search(fragment)
    return WEEKDAYS[m.group(1).lower()] if m else None


@dataclass
class DatedEntry:
    label: str
    start: dt.date | None
    end: dt.date | None
    raw: str


_IMPORTANT_LINE_RE = re.compile(
    r"^\s*(?P<dates>[A-Za-z]+\s+\d{1,2}\s*(?:st|nd|rd|th)?"
    r"(?:\s*[-–—]\s*(?:[A-Za-z]+\s+)?\d{1,2}\s*(?:st|nd|rd|th)?)?)\s*[:\-–—]\s*(?P<label>.+?)\s*$"
)


def parse_important_dates(lines: list[str], term: Term | None) -> list[DatedEntry]:
    """read a standalone "important dates" block.

    the label often sits on the line after its date, so a date line with nothing
    following the colon takes its label from the next non-empty line.
    """
    entries: list[DatedEntry] = []
    index = 0
    while index < len(lines):
        line = lines[index].strip()
        index += 1
        if not line:
            continue

        m = _IMPORTANT_LINE_RE.match(line)
        label = None
        date_part = None
        if m:
            date_part, label = m.group("dates"), m.group("label").strip()
        elif re.match(r"^[A-Za-z]+\s+\d{1,2}\s*(?:st|nd|rd|th)?\s*[-–—:]?\s*$", line):
            date_part = line.rstrip(" :-–—")
            while index < len(lines) and not lines[index].strip():
                index += 1
            if index < len(lines):
                label = lines[index].strip()
                index += 1

        if not date_part or not label:
            continue

        found = list(iter_dates(date_part, term))
        end = found[1] if len(found) > 1 else None
        if end is None and found:
            # "March 7th - 11th" leaves the month off the second day
            m_range = re.search(
                r"[-–—]\s*(?:[A-Za-z]+\s+)?(\d{1,2})\s*(?:st|nd|rd|th)?\s*$", date_part
            )
            if m_range:
                day = int(m_range.group(1))
                if day != found[0].day:
                    end = _safe_date(found[0].year, found[0].month, day)

        entries.append(
            DatedEntry(label=label, start=found[0] if found else None, end=end, raw=line)
        )
    return entries
