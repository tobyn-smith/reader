"""what is assigned this week, what has arrived, what is missing, what is due."""

from __future__ import annotations

import datetime as dt
import json
import sqlite3
from dataclasses import dataclass, field

from . import db


@dataclass
class ReadingStatus:
    work_id: int
    label: str
    requirement_level: str
    present: bool
    access_note: str | None = None
    content_warning: str | None = None
    page_range: str | None = None


@dataclass
class SessionStatus:
    course_code: str
    week_number: int | None
    meeting_date: dt.date | None
    sub_session_label: str | None
    topic: str | None
    session_type: str
    readings: list[ReadingStatus] = field(default_factory=list)

    @property
    def missing(self) -> list[ReadingStatus]:
        return [r for r in self.readings if not r.present]

    @property
    def header(self) -> str:
        bits = [self.course_code]
        if self.week_number:
            bits.append(f"Week {self.week_number}")
        if self.meeting_date:
            bits.append(f"({short_date(self.meeting_date)})")
        if self.sub_session_label:
            bits.append(self.sub_session_label)
        if self.topic:
            bits.append(self.topic)
        return " ".join(bits)


def short_date(value: dt.date | None) -> str:
    if value is None:
        return ""
    return f"{value.month}/{value.day}"


def cite_label(row: sqlite3.Row) -> str:
    """a one line label: surname, year, short title. enough to recognise."""
    authors = []
    try:
        authors = json.loads(row["authors"] or "[]")
    except (TypeError, ValueError):
        authors = []
    surname = ""
    if authors:
        first = authors[0]
        surname = first.get("surname") or first.get("literal") or ""
        if len(authors) > 1:
            surname += " et al" if len(authors) > 2 else f" and {authors[1].get('surname', '')}"

    parts = [p for p in (surname, str(row["year"]) if row["year"] else "") if p]
    head = " ".join(parts)
    title = (row["title"] or row["raw_source_text"] or "").strip()
    if len(title) > 62:
        title = title[:59].rstrip() + "..."
    return f"{head}, {title}" if head and title else (head or title or "untitled")


def parse_date(value: str | None) -> dt.date | None:
    if not value:
        return None
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        return None


def week_status(
    conn: sqlite3.Connection,
    *,
    course_code: str | None = None,
    week: int | None = None,
    on: dt.date | None = None,
) -> list[SessionStatus]:
    on = on or dt.date.today()
    out: list[SessionStatus] = []

    for course in db.courses(conn):
        if course_code and course["code"].replace(" ", "").lower() != course_code.replace(" ", "").lower():
            continue

        sessions = db.sessions_for(conn, course["id"])
        chosen = _choose(sessions, week, on)
        for session in chosen:
            status = SessionStatus(
                course_code=course["code"],
                week_number=session["week_number"],
                meeting_date=parse_date(session["meeting_date"]),
                sub_session_label=session["sub_session_label"],
                topic=session["topic"],
                session_type=session["session_type"],
            )
            for reading in db.readings_for(conn, session["id"]):
                status.readings.append(
                    ReadingStatus(
                        work_id=reading["work_id"],
                        label=cite_label(reading),
                        requirement_level=reading["requirement_level"],
                        present=bool(reading["document_count"]),
                        access_note=reading["access_note"],
                        content_warning=reading["content_warning"],
                        page_range=reading["page_range"],
                    )
                )
            out.append(status)
    return out


def _choose(sessions: list[sqlite3.Row], week: int | None, on: dt.date) -> list[sqlite3.Row]:
    if week is not None:
        return [s for s in sessions if s["week_number"] == week]

    dated = [(parse_date(s["meeting_date"]), s) for s in sessions]
    upcoming = [(d, s) for d, s in dated if d and d >= on]
    if upcoming:
        target = min(d for d, _ in upcoming)
        same_week = [s for d, s in dated if d and 0 <= (d - target).days < 7]
        return same_week or [s for d, s in upcoming if d == target]

    past = [(d, s) for d, s in dated if d]
    if past:
        target = max(d for d, _ in past)
        return [s for d, s in past if d == target]
    return sessions[:1]


def upcoming_deliverables(
    conn: sqlite3.Connection, *, within_days: int = 14, on: dt.date | None = None
) -> list[sqlite3.Row]:
    on = on or dt.date.today()
    horizon = on + dt.timedelta(days=within_days)
    out = []
    for row in db.all_deliverables(conn):
        due = parse_date(row["due_date"])
        if row["recurrence"] and row["recurrence"] != "see schedule":
            out.append(row)
        elif due and on <= due <= horizon:
            out.append(row)
    return out


def render(statuses: list[SessionStatus], deliverables: list[sqlite3.Row]) -> str:
    """the plain text week view. this is the thing that gets looked at most."""
    lines: list[str] = []
    for status in statuses:
        head = [status.course_code]
        if status.week_number:
            head.append(f"Week {status.week_number}")
        if status.meeting_date:
            head.append(f"({short_date(status.meeting_date)})")
        if status.sub_session_label:
            head.append(status.sub_session_label)
        if status.topic:
            head.append(status.topic)
        lines.append(" ".join(head))

        if not status.readings:
            lines.append(f"  no readings assigned ({status.session_type.replace('_', ' ')})")
        for reading in status.readings:
            mark = "x" if reading.present else " "
            suffix = ""
            if not reading.present:
                suffix = "   MISSING"
                if reading.access_note:
                    suffix += f" [{reading.access_note}]"
            level = "" if reading.requirement_level == "required" else f" ({reading.requirement_level})"
            lines.append(f"  [{mark}] {reading.label}{level}{suffix}")
            if reading.content_warning:
                lines.append(f"      content warning: {reading.content_warning}")
        lines.append("")

    if deliverables:
        lines.append("due")
        for row in deliverables:
            when = row["recurrence"] or short_date(parse_date(row["due_date"]))
            time = f" {row['due_time'][:5]}" if row["due_time"] else ""
            lines.append(f"  {row['course_code']}  {row['title']}  {when}{time}")

    return "\n".join(lines).rstrip() or "nothing scheduled"
