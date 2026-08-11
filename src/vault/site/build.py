"""render the whole site to a directory.

the public build reads data/public.json and nothing else, so it runs in ci with
no database present. the private build reads the database and adds full text,
briefs and every note. both use the same functions below; only the payload
differs.
"""

from __future__ import annotations

import datetime as dt
import json
import shutil
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from .. import db, publish
from .render import (
    authors_label,
    citation_line,
    esc,
    nav,
    page,
    short_date,
    slug,
    stance_note,
    table,
)

ASSETS = Path(__file__).parent / "assets"


@dataclass
class BuildReport:
    target: Path
    private: bool
    pages: int = 0
    courses: int = 0
    withheld: list[str] = field(default_factory=list)
    included: list[str] = field(default_factory=list)

    def render(self) -> str:
        kind = "private" if self.private else "public"
        lines = [
            f"{kind} build written to {self.target}",
            f"  courses {self.courses}, pages {self.pages}",
            "  included: " + (", ".join(self.included) or "nothing"),
            "  withheld: " + (", ".join(self.withheld) or "nothing"),
        ]
        return "\n".join(lines)


def load_public_payload(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def build_private_payload(conn: sqlite3.Connection) -> dict:
    """everything, for local use only."""
    payload, _ = publish.build_public_payload(conn)

    for course in payload["courses"]:
        for policy in db.policies_for(conn, course["id"]):
            pass
        row = conn.execute(
            "select instructor_email, location from course where id = ?", (course["id"],)
        ).fetchone()
        if row:
            course["instructor_email"] = row["instructor_email"]
            course["location"] = row["location"]

        for work in course["works"]:
            brief = db.brief_for(conn, work["id"])
            if brief:
                work["brief"] = {
                    "markdown": brief["markdown"],
                    "generated_by": brief["generated_by"],
                }
            work["notes"] = [dict(n) for n in db.notes_for(conn, work["id"])]
            work["passages"] = [
                dict(r)
                for r in conn.execute(
                    "select c.page_number, c.body from chunk c"
                    " join document d on d.id = c.document_id"
                    " where d.work_id = ? order by c.ordinal limit 400",
                    (work["id"],),
                )
            ]
    return payload


def build(payload: dict, target: Path, *, private: bool = False) -> BuildReport:
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)

    courses = payload.get("courses", [])
    report = BuildReport(target=target, private=private, courses=len(courses))
    report.included = ["schedule", "citations", "deliverables", "bibliography"]
    if private:
        report.included += ["full text", "briefs", "all notes"]
        report.withheld = []
    else:
        report.included += ["notes marked shareable"]
        report.withheld = [
            "extracted reading text",
            "briefs",
            "notes not marked shareable",
            "instructor email and location",
        ]

    _copy_assets(target)

    _write(target / "index.html", _index(courses), report)
    _write(target / "deadlines.html", _deadlines(courses), report)
    _write(target / "search.html", _search(courses), report)

    for course in courses:
        base = target / "course" / slug(course["code"])
        base.mkdir(parents=True, exist_ok=True)
        _write(base / "index.html", _course(course, courses), report)
        _write(base / "bibliography.html", _bibliography(course, courses), report)
        for session in course.get("sessions", []):
            number = session.get("week_number")
            if number is None:
                continue
            name = f"week-{number:02d}.html"
            _write(base / name, _week(course, courses, number), report)
        for work in course.get("works", []):
            works_dir = base / "work"
            works_dir.mkdir(parents=True, exist_ok=True)
            _write(works_dir / f"{work['id']}.html", _work(course, courses, work, private), report)

    return report


def _write(path: Path, content: str, report: BuildReport) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    report.pages += 1


def _copy_assets(target: Path) -> None:
    for asset in ASSETS.glob("*"):
        shutil.copy(asset, target / asset.name)


def _course_depth(course: dict) -> int:
    return 2


def _index(courses: list[dict]) -> str:
    rows = []
    for course in courses:
        link = f'<a href="course/{slug(course["code"])}/index.html">{esc(course["code"])}</a>'
        term = f"{esc(course.get('term') or '')} {esc(course.get('year') or '')}".strip()
        weeks = len({s.get("week_number") for s in course.get("sessions", []) if s.get("week_number")})
        readings = sum(len(s.get("readings", [])) for s in course.get("sessions", []))
        rows.append([link, esc(course.get("title") or ""), term, str(weeks), str(readings)])

    body = ["<h1>Courses</h1>", table(["Course", "Title", "Term", "Weeks", "Readings"], rows)]

    upcoming = _collect_deliverables(courses)[:12]
    if upcoming:
        body.append("<h2>Next deadlines</h2>")
        body.append(
            table(
                ["Due", "Course", "Item", "Weight"],
                [
                    [
                        esc(d["when"]),
                        esc(d["course"]),
                        esc(d["title"]),
                        esc(_weight_label(d["weight"])),
                    ]
                    for d in upcoming
                ],
            )
        )
    return page("Courses", "\n".join(body), depth=0, nav=nav(courses, 0))


def _weight_label(value) -> str:
    if not value:
        return ""
    return f"{value:g}%"


def _collect_deliverables(courses: list[dict]) -> list[dict]:
    """graded work that can be placed in time.

    a sign-up or presentation line with no date and no weight is a session
    event, not a deadline. it belongs on the week it happens and only clutters
    a date-ordered list, so it is left out here.
    """
    out = []
    for course in courses:
        for item in course.get("deliverables", []):
            dated = bool(item.get("due_date"))
            recurring = bool(item.get("recurrence"))
            weighted = bool(item.get("weight_percent"))
            if not dated and not recurring and not weighted:
                continue
            out.append(
                {
                    "sort": item.get("due_date") or "9999-99-99",
                    "when": short_date(item.get("due_date")) or (item.get("recurrence") or ""),
                    "course": course["code"],
                    "title": item.get("title", ""),
                    "weight": item.get("weight_percent"),
                    "time": (item.get("due_time") or "")[:5],
                    "group": "dated" if dated else ("recurring" if recurring else "undated"),
                }
            )
    return sorted(out, key=lambda d: (d["sort"], d["course"]))


def _deadlines(courses: list[dict]) -> str:
    items = _collect_deliverables(courses)

    def rows_for(group: str) -> list[list[str]]:
        return [
            [esc(d["when"]), esc(d["time"]), esc(d["course"]), esc(d["title"]),
             esc(_weight_label(d["weight"]))]
            for d in items
            if d["group"] == group
        ]

    body = [
        "<h1>Deadlines</h1>",
        '<p><a href="pdf/deadlines.pdf">Print PDF</a></p>',
        table(["Due", "Time", "Course", "Item", "Weight"], rows_for("dated")),
    ]

    recurring = rows_for("recurring")
    if recurring:
        body.append("<h2>Recurring</h2>")
        body.append(table(["Repeats", "Time", "Course", "Item", "Weight"], recurring))

    undated = rows_for("undated")
    if undated:
        body.append("<h2>No date in the syllabus</h2>")
        body.append(table(["", "", "Course", "Item", "Weight"], undated))

    return page("Deadlines", "\n".join(body), depth=0, nav=nav(courses, 0))


def _search(courses: list[dict]) -> str:
    body = [
        "<h1>Search</h1>",
        '<div id="search"></div>',
        '<script>window.addEventListener("DOMContentLoaded",function(){'
        'if(window.PagefindUI){new PagefindUI({element:"#search",showImages:false});}'
        'else{document.getElementById("search").textContent='
        '"Search index not built. Run the build with pagefind available.";}});</script>',
    ]
    return page("Search", "\n".join(body), depth=0, nav=nav(courses, 0), search=True)


def _course(course: dict, courses: list[dict]) -> str:
    works = {w["id"]: w for w in course.get("works", [])}
    body = [f"<h1>{esc(course['code'])} {esc(course.get('title') or '')}</h1>"]

    meta = []
    if course.get("term"):
        meta.append(f"{esc(course['term'])} {esc(course.get('year') or '')}".strip())
    if course.get("instructor_name"):
        meta.append(esc(course["instructor_name"]))
    if course.get("meeting_time"):
        meta.append(esc(course["meeting_time"]))
    if course.get("citation_style"):
        meta.append(f"citation style: {esc(course['citation_style'])}")
    if meta:
        body.append(f'<p class="meta">{" &middot; ".join(meta)}</p>')

    body.append(stance_note(course.get("ai_stance")))
    code = slug(course["code"])
    body.append(
        f'<p><a href="bibliography.html">Bibliography</a> '
        f'&middot; <a href="../../deadlines.html">Deadlines</a> '
        f'&middot; <a href="../../pdf/{code}-semester-plan.pdf">Semester plan PDF</a> '
        f'&middot; <a href="../../pdf/{code}-bibliography.pdf">Bibliography PDF</a></p>'
    )

    body.append("<h2>Schedule</h2>")
    rows = []
    for session in course.get("sessions", []):
        number = session.get("week_number")
        label = f"Week {number}" if number else ""
        if number:
            label = f'<a href="week-{number:02d}.html">{label}</a>'
        sub = esc(session.get("sub_session_label") or "")
        date = short_date(session.get("meeting_date"))
        topic = esc(session.get("topic") or "")
        readings = session.get("readings", [])
        if readings:
            items = "<br>".join(
                _reading_cell(r, works) for r in readings
            )
        else:
            items = f'<span class="quiet">{esc(session.get("session_type", "").replace("_", " "))}</span>'
        rows.append([label, date, sub, topic, items])

    body.append(table(["Week", "Date", "", "Topic", "Readings"], rows, css="schedule"))
    return page(
        f"{course['code']} schedule", "\n".join(body), depth=2, nav=nav(courses, 2)
    )


def _reading_cell(reading: dict, works: dict) -> str:
    work = works.get(reading.get("work_id"), {})
    label = citation_line(work) or "unparsed"
    link = f'<a href="work/{reading.get("work_id")}.html">{esc(label)}</a>'
    extras = []
    level = reading.get("requirement_level")
    if level and level != "required":
        extras.append(esc(level))
    if reading.get("page_range"):
        extras.append(f"pp. {esc(reading['page_range'])}")
    if not reading.get("has_document"):
        extras.append('<span class="missing">missing</span>')
    if reading.get("content_warning"):
        extras.append(f'<span class="warn">content warning: {esc(reading["content_warning"])}</span>')
    tail = f' <span class="tags">{" &middot; ".join(extras)}</span>' if extras else ""
    return link + tail


def _week(course: dict, courses: list[dict], number: int) -> str:
    works = {w["id"]: w for w in course.get("works", [])}
    sessions = [s for s in course.get("sessions", []) if s.get("week_number") == number]
    body = [f"<h1>{esc(course['code'])} Week {number}</h1>"]
    body.append(stance_note(course.get("ai_stance")))
    code = slug(course["code"])
    body.append(f'<p><a href="../../pdf/{code}-week-{number:02d}.pdf">Week sheet PDF</a></p>')

    for session in sessions:
        head = []
        if session.get("meeting_date"):
            head.append(short_date(session["meeting_date"]))
        if session.get("sub_session_label"):
            head.append(esc(session["sub_session_label"]))
        if session.get("topic"):
            head.append(esc(session["topic"]))
        body.append(f"<h2>{' '.join(head) or 'Session'}</h2>")

        rows = []
        for reading in session.get("readings", []):
            work = works.get(reading.get("work_id"), {})
            have = "" if reading.get("has_document") else '<span class="missing">missing</span>'
            rows.append(
                [
                    have,
                    f'<a href="work/{reading.get("work_id")}.html">{esc(citation_line(work))}</a>',
                    esc(reading.get("requirement_level") or ""),
                    esc(reading.get("page_range") or ""),
                    esc(reading.get("access_note") or ""),
                ]
            )
        if rows:
            body.append(table(["", "Reading", "Level", "Pages", "Access"], rows))
        else:
            body.append(
                f'<p class="empty">No readings assigned '
                f'({esc(session.get("session_type", "").replace("_", " "))}).</p>'
            )

        warnings = [r for r in session.get("readings", []) if r.get("content_warning")]
        for reading in warnings:
            body.append(f'<p class="warn">Content warning: {esc(reading["content_warning"])}</p>')

    due = [d for d in _collect_deliverables([course])]
    if due:
        body.append("<h2>Due</h2>")
        body.append(
            table(
                ["Due", "Item", "Weight"],
                [[esc(d["when"]), esc(d["title"]), esc(_weight_label(d["weight"]))] for d in due],
            )
        )

    return page(f"{course['code']} week {number}", "\n".join(body), depth=2, nav=nav(courses, 2))


def _bibliography(course: dict, courses: list[dict]) -> str:
    works = sorted(
        course.get("works", []),
        key=lambda w: (
            (w.get("authors") or [{}])[0].get("surname")
            or (w.get("authors") or [{}])[0].get("literal")
            or w.get("title")
            or ""
        ).lower(),
    )
    style = course.get("citation_style") or "default"
    body = [
        f"<h1>{esc(course['code'])} bibliography</h1>",
        f'<p class="meta">Style: {esc(style)}. {len(works)} works.</p>',
        '<ol class="bib">',
    ]
    for work in works:
        body.append(f"<li>{esc(citation_line(work))}</li>")
    body.append("</ol>")
    return page(f"{course['code']} bibliography", "\n".join(body), depth=2, nav=nav(courses, 2))


def _work(course: dict, courses: list[dict], work: dict, private: bool) -> str:
    body = [f"<h1>{esc(work.get('title') or 'Untitled')}</h1>"]
    body.append(f'<p class="meta">{esc(citation_line(work))}</p>')
    body.append(stance_note(course.get("ai_stance")))

    facts = []
    for label, key in (
        ("Type", "work_type"), ("Year", "year"), ("Container", "container"),
        ("Publisher", "publisher"), ("Volume", "volume"), ("Issue", "issue"),
        ("Pages", "pages"), ("Report number", "report_number"), ("DOI", "doi"),
    ):
        if work.get(key):
            facts.append([esc(label), esc(work[key])])
    if work.get("url"):
        facts.append(["Link", f'<a href="{esc(work["url"])}">{esc(work["url"])}</a>'])
    body.append(table(["Field", "Value"], facts))

    notes = work.get("notes") if private else []
    if notes:
        body.append("<h2>Notes</h2>")
        body.append(
            table(
                ["Page", "Note"],
                [[esc(n.get("page_number") or ""), esc(n.get("body", ""))] for n in notes],
            )
        )

    if private and work.get("brief"):
        brief = work["brief"]
        body.append("<h2>Brief</h2>")
        if str(brief.get("generated_by", "")).startswith("model:"):
            body.append(
                '<p class="flag">Model generated. Not for submission, '
                "and excluded from every public build.</p>"
            )
        body.append(f"<pre class=\"brief\">{esc(brief.get('markdown') or '')}</pre>")

    if private and work.get("passages"):
        body.append("<h2>Passages</h2>")
        body.append('<p class="meta">Local only. Never published.</p>')
        for passage in work["passages"][:80]:
            body.append(
                f'<p class="passage"><span class="page">p. {esc(passage["page_number"])}</span> '
                f'{esc(passage["body"])}</p>'
            )

    return page(work.get("title") or "Work", "\n".join(body), depth=3, nav=nav(courses, 3, private))
