"""sqlite access, kept behind one module.

every query in the project goes through here. postgres remains a mechanical swap
because nothing outside this file knows what the storage is, and db/postgres/
holds the same schema in the other dialect.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable

from .config import REPO_ROOT, Config

MIGRATIONS = REPO_ROOT / "db" / "migrations"


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("pragma foreign_keys = on")
    conn.execute("pragma journal_mode = wal")
    return conn


def migrate(conn: sqlite3.Connection, directory: Path = MIGRATIONS) -> list[str]:
    conn.execute(
        "create table if not exists schema_migration ("
        " name text primary key, applied_at text not null default (datetime('now')))"
    )
    done = {row["name"] for row in conn.execute("select name from schema_migration")}
    applied: list[str] = []
    for script in sorted(directory.glob("*.sql")):
        if script.name in done:
            continue
        conn.executescript(script.read_text(encoding="utf-8"))
        conn.execute("insert into schema_migration (name) values (?)", (script.name,))
        conn.commit()
        applied.append(script.name)
    return applied


def open_vault(config: Config) -> sqlite3.Connection:
    conn = connect(config.database)
    migrate(conn)
    return conn


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def write_parse(conn: sqlite3.Connection, parsed: dict) -> int:
    """commit a confirmed parse. re-parsing the same file replaces it.

    replacing rather than appending is deliberate: a syllabus is parsed once per
    term, and a second run means the first one was wrong.
    """
    course = parsed["course"]
    cursor = conn.execute(
        "select id from course where source_file_hash = ?", (parsed["file_hash"],)
    )
    existing = cursor.fetchone()
    if existing:
        conn.execute("delete from course where id = ?", (existing["id"],))

    course_id = conn.execute(
        """
        insert into course (
            code, title, term, year, instructor_name, instructor_email,
            meeting_time, location, site_url, citation_style,
            source_file_hash, source_filename
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            course.get("code") or "unknown",
            course.get("title") or "untitled",
            course.get("term"),
            course.get("year"),
            course.get("instructor_name"),
            course.get("instructor_email"),
            course.get("meeting_time"),
            course.get("location"),
            course.get("site_url"),
            course.get("citation_style"),
            parsed["file_hash"],
            parsed["source_filename"],
        ),
    ).lastrowid

    for policy in parsed.get("policies", []):
        conn.execute(
            "insert into course_policy (course_id, policy_type, ai_stance, heading, body,"
            " page_number, confidence) values (?, ?, ?, ?, ?, ?, ?)",
            (
                course_id,
                policy["policy_type"],
                policy.get("ai_stance"),
                policy.get("heading"),
                policy.get("body", ""),
                policy.get("page_number"),
                policy.get("confidence", 1.0),
            ),
        )

    for session in parsed.get("sessions", []):
        session_id = conn.execute(
            "insert into session (course_id, week_number, meeting_date, sub_session_label,"
            " topic, section_heading, session_type, ordinal, page_number, raw_source_text,"
            " confidence) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                course_id,
                session.get("week_number"),
                session.get("meeting_date"),
                session.get("sub_session_label"),
                session.get("topic"),
                session.get("section_heading"),
                session.get("session_type", "reading"),
                session["ordinal"],
                session.get("page_number"),
                session.get("raw_source_text"),
                session.get("confidence", 1.0),
            ),
        ).lastrowid

        for reading in session.get("readings", []):
            work_id = _upsert_work(conn, reading["work"])
            conn.execute(
                "insert into assigned_reading (session_id, work_id, requirement_level,"
                " page_range, access_note, content_warning, ordinal, raw_source_text,"
                " confidence) values (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    session_id,
                    work_id,
                    reading.get("requirement_level", "required"),
                    reading.get("page_range"),
                    reading.get("access_note"),
                    reading.get("content_warning"),
                    reading["ordinal"],
                    reading.get("raw_source_text"),
                    reading.get("confidence", 1.0),
                ),
            )

    for item in parsed.get("deliverables", {}).get("items", []):
        conn.execute(
            "insert into deliverable (course_id, title, kind, due_date, due_time, recurrence,"
            " weight_percent, page_limit, word_limit, format_notes, requirements_text,"
            " source_zone, page_number, confidence)"
            " values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                course_id,
                item["title"],
                item.get("kind", "other"),
                item.get("due_date"),
                item.get("due_time"),
                item.get("recurrence"),
                item.get("weight_percent"),
                item.get("page_limit"),
                item.get("word_limit"),
                item.get("format_notes"),
                item.get("requirements_text"),
                item.get("source_zone"),
                item.get("page_number"),
                item.get("confidence", 1.0),
            ),
        )

    run_id = conn.execute(
        "insert into parse_run (course_id, source_file_hash, source_filename,"
        " schedule_structure, committed_at) values (?, ?, ?, ?, datetime('now'))",
        (course_id, parsed["file_hash"], parsed["source_filename"], parsed["structure"]),
    ).lastrowid

    for item in parsed.get("review", []):
        conn.execute(
            "insert into parse_review (parse_run_id, entity_type, entity_ref, field_name,"
            " source_text, guess, confidence, reason, decision, decided_value, decided_at)"
            " values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))",
            (
                run_id,
                item["entity_type"],
                item.get("entity_ref"),
                item.get("field_name"),
                item.get("source_text", ""),
                _json(item.get("guess")),
                item.get("confidence", 0.0),
                item.get("reason", ""),
                item.get("decision", "accepted"),
                _json(item.get("decided_value")),
            ),
        )

    conn.commit()
    return course_id


def _upsert_work(conn: sqlite3.Connection, work: dict) -> int:
    """reuse an existing work when the same thing is assigned twice."""
    signature = work.get("signature")
    doi = work.get("doi")
    if doi:
        row = conn.execute(
            "select id from work where lower(doi) = lower(?)", (doi,)
        ).fetchone()
        if row:
            return row["id"]
    if signature and signature.strip("| "):
        row = conn.execute("select id from work where signature = ?", (signature,)).fetchone()
        if row:
            return row["id"]

    return conn.execute(
        "insert into work (authors, title, container, publisher, year, year_end,"
        " year_is_open, volume, issue, pages, doi, url, report_number, work_type,"
        " rendered_citation, raw_source_text, matched_pattern, signature, confidence)"
        " values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            _json(work.get("authors", [])),
            work.get("title"),
            work.get("container"),
            work.get("publisher"),
            work.get("year"),
            work.get("year_end"),
            1 if work.get("year_is_open") else 0,
            work.get("volume"),
            work.get("issue"),
            work.get("pages"),
            work.get("doi"),
            work.get("url"),
            work.get("report_number"),
            work.get("work_type", "unknown"),
            work.get("rendered_citation"),
            work.get("raw_source_text", ""),
            work.get("matched_pattern"),
            work.get("signature"),
            work.get("confidence", 1.0),
        ),
    ).lastrowid


def courses(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            "select c.*, (select ai_stance from course_policy p where p.course_id = c.id"
            "   and p.policy_type = 'ai_use' limit 1) as ai_stance"
            " from course c order by c.year desc, c.term, c.code"
        )
    )


def sessions_for(conn: sqlite3.Connection, course_id: int) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            "select * from session where course_id = ? order by ordinal", (course_id,)
        )
    )


def readings_for(conn: sqlite3.Connection, session_id: int) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            "select ar.*, w.authors, w.title, w.container, w.year, w.year_end,"
            " w.year_is_open, w.volume, w.issue, w.pages as work_pages, w.doi, w.url,"
            " w.report_number, w.work_type, w.rendered_citation, w.matched_pattern,"
            " w.id as work_id,"
            " (select count(*) from document d where d.work_id = w.id) as document_count"
            " from assigned_reading ar join work w on w.id = ar.work_id"
            " where ar.session_id = ? order by ar.ordinal",
            (session_id,),
        )
    )


def deliverables_for(conn: sqlite3.Connection, course_id: int) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            "select * from deliverable where course_id = ?"
            " order by case when due_date is null then 1 else 0 end, due_date, title",
            (course_id,),
        )
    )


def all_deliverables(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            "select d.*, c.code as course_code from deliverable d"
            " join course c on c.id = d.course_id"
            " order by case when d.due_date is null then 1 else 0 end, d.due_date"
        )
    )


def policies_for(conn: sqlite3.Connection, course_id: int) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            "select * from course_policy where course_id = ? order by"
            " case policy_type when 'ai_use' then 0 when 'late_work' then 1"
            " when 'attendance' then 2 when 'grading_scale' then 3"
            " when 'boilerplate' then 9 else 5 end",
            (course_id,),
        )
    )


def notes_for(conn: sqlite3.Connection, work_id: int) -> list[sqlite3.Row]:
    return list(
        conn.execute("select * from note where work_id = ? order by page_number", (work_id,))
    )


def brief_for(conn: sqlite3.Connection, work_id: int) -> sqlite3.Row | None:
    return conn.execute("select * from brief where work_id = ?", (work_id,)).fetchone()


def search_chunks(conn: sqlite3.Connection, query: str, limit: int = 40) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            "select c.page_number, c.body, c.kind, d.filename, w.title, w.id as work_id,"
            " snippet(chunk_fts, 0, '[', ']', ' ... ', 18) as excerpt"
            " from chunk_fts join chunk c on c.id = chunk_fts.rowid"
            " join document d on d.id = c.document_id"
            " left join work w on w.id = d.work_id"
            " where chunk_fts match ? order by rank limit ?",
            (query, limit),
        )
    )
