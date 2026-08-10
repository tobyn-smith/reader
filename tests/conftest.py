import sqlite3
from pathlib import Path

import pytest

from vault import db as db_mod

REPO = Path(__file__).resolve().parents[1]

SENTINEL_CHUNK = "XCHUNKLEAKX quiet fields of unpublished prose"
SENTINEL_BRIEF = "XBRIEFLEAKX a model wrote this and it must stay home"
SENTINEL_EMAIL = "leak.target@example.edu"


@pytest.fixture
def vault_conn(tmp_path) -> sqlite3.Connection:
    conn = db_mod.connect(tmp_path / "vault.sqlite")
    db_mod.migrate(conn, REPO / "db" / "migrations")
    _seed(conn)
    return conn


def _seed(conn: sqlite3.Connection) -> None:
    """a small invented course with one of everything the filter must catch."""
    course_id = conn.execute(
        "insert into course (code, title, term, year, instructor_name, instructor_email,"
        " meeting_time, location, source_file_hash, source_filename)"
        " values ('DEMO 6100', 'Seminar in Example Studies', 'fall', 2030,"
        " 'Alex Instructor', ?, 'Thu 3:00-5:45', 'Building 4 Room 101',"
        " 'hash-demo-6100', 'demo.pdf')",
        (SENTINEL_EMAIL,),
    ).lastrowid

    conn.execute(
        "insert into course_policy (course_id, policy_type, ai_stance, body)"
        " values (?, 'ai_use', 'prohibited', 'AI tools must not be used in this course.')",
        (course_id,),
    )

    session_id = conn.execute(
        "insert into session (course_id, week_number, meeting_date, topic, ordinal)"
        " values (?, 2, '2030-09-05', 'Foundations', 0)",
        (course_id,),
    ).lastrowid
    conn.execute(
        "insert into session (course_id, week_number, meeting_date, topic, session_type, ordinal)"
        " values (?, 3, '2030-09-12', 'Spring Break', 'holiday', 1)",
        (course_id,),
    )

    work_id = conn.execute(
        "insert into work (authors, title, container, year, volume, issue, pages,"
        " work_type, raw_source_text, signature)"
        " values ('[{\"surname\": \"Rivera\", \"given\": \"Sam\"}]',"
        " 'A Study of Examples', 'Journal of Demonstrations', 2019, '12', '3',"
        " '101-140', 'journal_article', 'Rivera, Sam. 2019. ...', 'rivera|2019|a study of examples')"
    ).lastrowid
    conn.execute(
        "insert into assigned_reading (session_id, work_id, requirement_level, ordinal,"
        " access_note) values (?, ?, 'required', 0, 'pdf on course site')",
        (session_id, work_id),
    )

    missing_work = conn.execute(
        "insert into work (authors, title, year, work_type, raw_source_text, signature)"
        " values ('[{\"surname\": \"Okafor\", \"given\": \"Jo\"}]',"
        " 'The Unread Reading', 2021, 'journal_article', 'Okafor, Jo. 2021 ...',"
        " 'okafor|2021|the unread reading')"
    ).lastrowid
    conn.execute(
        "insert into assigned_reading (session_id, work_id, requirement_level, ordinal)"
        " values (?, ?, 'required', 1)",
        (session_id, missing_work),
    )

    conn.execute(
        "insert into deliverable (course_id, title, kind, due_date, due_time, weight_percent,"
        " page_limit, requirements_text)"
        " values (?, 'Weekly memo', 'checklist', '2030-09-05', '09:00', 30, 5,"
        " 'Submit a memo before class each week.')",
        (course_id,),
    )

    document_id = conn.execute(
        "insert into document (work_id, file_hash, filename, page_count)"
        " values (?, 'hash-doc-1', 'rivera-2019.pdf', 40)",
        (work_id,),
    ).lastrowid
    conn.execute(
        "insert into chunk (document_id, page_number, ordinal, body) values (?, 7, 0, ?)",
        (document_id, SENTINEL_CHUNK),
    )

    conn.execute(
        "insert into brief (work_id, course_id, generated_by, markdown)"
        " values (?, ?, 'model:test', ?)",
        (work_id, course_id, SENTINEL_BRIEF),
    )

    conn.execute(
        "insert into note (work_id, page_number, body, shareable) values (?, 7,"
        " 'private thought, stays home', 0)",
        (work_id,),
    )
    conn.execute(
        "insert into note (work_id, page_number, body, shareable) values (?, 9,"
        " 'shareable observation', 1)",
        (work_id,),
    )
    conn.commit()
