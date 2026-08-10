"""what may leave the machine.

github pages on any realistic plan is world readable, so the public build is
treated as published to the world. the filter here is default deny: a field
reaches the export only if it is named in ALLOWED. adding a column to the schema
does not publish it, and the allowlist test fails until someone decides.

the stronger guarantee is upstream of this file. ci builds the public site from
data/public.json alone and never sees the database, so it cannot leak what it
cannot read.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from . import db

# entity name -> exactly the fields allowed out. nothing else is copied, ever.
ALLOWED: dict[str, set[str]] = {
    "course": {
        "id", "code", "title", "term", "year", "instructor_name",
        "meeting_time", "site_url", "citation_style", "ai_stance",
    },
    "session": {
        "id", "week_number", "meeting_date", "sub_session_label", "topic",
        "section_heading", "session_type", "ordinal",
    },
    "work": {
        "id", "authors", "title", "container", "publisher", "year", "year_end",
        "year_is_open", "volume", "issue", "pages", "doi", "url",
        "report_number", "work_type", "rendered_citation",
    },
    "assigned_reading": {
        "ordinal", "requirement_level", "page_range", "access_note",
        "content_warning", "work_id", "has_document",
    },
    "deliverable": {
        "id", "title", "kind", "due_date", "due_time", "recurrence",
        "weight_percent", "page_limit", "word_limit", "format_notes",
    },
    "policy": {"policy_type", "ai_stance", "heading", "body", "page_number"},
    "note": {"id", "work_id", "page_number", "body"},
}

# fields that exist in the schema and are deliberately held back. listed so the
# reason is written down rather than implied by absence.
WITHHELD = {
    "course.instructor_email": "personal contact detail",
    "course.location": "office and room location",
    "course.source_filename": "local filename",
    "chunk.body": "extracted text of someone else's copyrighted work",
    "brief.markdown": "model generated, opt in per course",
    "brief.body": "model generated, opt in per course",
    "note.shareable": "control flag, not content",
    "deliverable.requirements_text": "verbatim syllabus prose, kept local",
    "work.raw_source_text": "verbatim syllabus prose, kept local",
    "session.raw_source_text": "verbatim syllabus prose, kept local",
    "parse_review.source_text": "verbatim syllabus prose, kept local",
}


@dataclass
class ExportSummary:
    courses: int = 0
    sessions: int = 0
    works: int = 0
    deliverables: int = 0
    notes_included: int = 0
    notes_withheld: int = 0
    policies_included: int = 0
    courses_withheld: list[str] = field(default_factory=list)
    briefs_withheld: int = 0

    def render(self) -> str:
        lines = [
            "public export",
            f"  courses          {self.courses}",
            f"  sessions         {self.sessions}",
            f"  works            {self.works}",
            f"  deliverables     {self.deliverables}",
            f"  policies         {self.policies_included}",
            f"  notes included   {self.notes_included}",
            "withheld",
            f"  notes not marked shareable   {self.notes_withheld}",
            f"  briefs                       {self.briefs_withheld}",
            "  chunk text                   all",
            "  instructor email, location   all",
        ]
        if self.courses_withheld:
            lines.append(f"  courses flagged sensitive    {', '.join(self.courses_withheld)}")
        return "\n".join(lines)


def _pick(row, entity: str) -> dict:
    allowed = ALLOWED[entity]
    source = dict(row) if not isinstance(row, dict) else row
    return {key: value for key, value in source.items() if key in allowed}


def build_public_payload(conn: sqlite3.Connection) -> tuple[dict, ExportSummary]:
    summary = ExportSummary()
    payload: dict = {"schema": 1, "courses": []}

    for course_row in db.courses(conn):
        if course_row["sensitive"]:
            summary.courses_withheld.append(course_row["code"])
            continue

        course = _pick(course_row, "course")
        summary.courses += 1

        course["policies"] = []
        for policy in db.policies_for(conn, course_row["id"]):
            course["policies"].append(_pick(policy, "policy"))
            summary.policies_included += 1

        course["deliverables"] = []
        for item in db.deliverables_for(conn, course_row["id"]):
            course["deliverables"].append(_pick(item, "deliverable"))
            summary.deliverables += 1

        works: dict[int, dict] = {}
        course["sessions"] = []
        for session_row in db.sessions_for(conn, course_row["id"]):
            session = _pick(session_row, "session")
            session["readings"] = []
            for reading in db.readings_for(conn, session_row["id"]):
                entry = _pick(reading, "assigned_reading")
                entry["work_id"] = reading["work_id"]
                entry["has_document"] = bool(reading["document_count"])
                session["readings"].append(entry)

                if reading["work_id"] not in works:
                    works[reading["work_id"]] = _pick(reading, "work") | {
                        "id": reading["work_id"],
                        "authors": _load_authors(reading["authors"]),
                        "pages": reading["work_pages"],
                    }
            course["sessions"].append(session)
            summary.sessions += 1

        course["works"] = list(works.values())
        summary.works += len(works)

        course["notes"] = []
        for work_id in works:
            for note in db.notes_for(conn, work_id):
                if note["shareable"]:
                    course["notes"].append(_pick(note, "note"))
                    summary.notes_included += 1
                else:
                    summary.notes_withheld += 1
            if db.brief_for(conn, work_id) is not None:
                summary.briefs_withheld += 1

        payload["courses"].append(course)

    return payload, summary


def _load_authors(raw) -> list:
    if isinstance(raw, list):
        return raw
    try:
        return json.loads(raw or "[]")
    except (TypeError, ValueError):
        return []


def write_public_export(conn: sqlite3.Connection, target: Path) -> ExportSummary:
    payload, summary = build_public_payload(conn)
    violations = check_payload(payload)
    if violations:
        raise ValueError("export blocked, fields outside the allowlist: " + "; ".join(violations))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return summary


def check_payload(payload: dict) -> list[str]:
    """verify every key in a payload is allowlisted.

    run before writing and again in ci. a field nobody thought about fails here
    rather than appearing quietly on a public url.
    """
    problems: list[str] = []
    containers = {
        "sessions": "session",
        "works": "work",
        "deliverables": "deliverable",
        "policies": "policy",
        "notes": "note",
    }

    for course in payload.get("courses", []):
        for key in course:
            if key in containers:
                continue
            if key not in ALLOWED["course"]:
                problems.append(f"course.{key}")

        for container, entity in containers.items():
            for row in course.get(container, []):
                for key in row:
                    if container == "sessions" and key == "readings":
                        continue
                    if key not in ALLOWED[entity]:
                        problems.append(f"{entity}.{key}")

        for session in course.get("sessions", []):
            for reading in session.get("readings", []):
                for key in reading:
                    if key not in ALLOWED["assigned_reading"]:
                        problems.append(f"assigned_reading.{key}")

    return sorted(set(problems))


def check_export_file(path: Path) -> list[str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return check_payload(payload)
