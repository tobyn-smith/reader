"""print documents, built from the same data as the site.

weasyprint needs native pango libraries that are painless on linux and often
absent on windows. when they are missing the build says exactly that and skips
the pdfs rather than failing the whole site, and the github action, which runs
on ubuntu, produces them every time.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from pathlib import Path

from .render import citation_line, esc, short_date, slug

PRINT_CSS = Path(__file__).parent / "assets" / "print.css"


@dataclass
class PdfReport:
    written: list[Path]
    skipped_reason: str | None = None


def _available() -> tuple[bool, str]:
    try:
        import weasyprint  # noqa: F401

        return True, ""
    except ImportError:
        return False, "weasyprint is not installed"
    except OSError as error:
        return False, f"weasyprint cannot load its native libraries: {error}"


def build_pdfs(payload: dict, target: Path, *, generated_on: dt.date | None = None) -> PdfReport:
    ok, reason = _available()
    if not ok:
        return PdfReport(written=[], skipped_reason=reason)

    import weasyprint

    generated = (generated_on or dt.date.today()).isoformat()
    css = weasyprint.CSS(filename=str(PRINT_CSS))
    # the generation date goes into the running footer here rather than via
    # string-set, which never fires for hidden elements
    stamp = weasyprint.CSS(
        string='@page { @bottom-left { content: "Generated %s"; font-size: 8pt; } }' % generated
    )
    target.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    def emit(name: str, html: str) -> None:
        path = target / name
        weasyprint.HTML(string=html).write_pdf(str(path), stylesheets=[css, stamp])
        written.append(path)

    courses = payload.get("courses", [])
    for course in courses:
        code = slug(course["code"])
        emit(f"{code}-semester-plan.pdf", semester_plan_html(course, generated))
        emit(f"{code}-bibliography.pdf", bibliography_html(course, generated))
        for number in sorted(
            {s["week_number"] for s in course.get("sessions", []) if s.get("week_number")}
        ):
            emit(f"{code}-week-{number:02d}.pdf", week_sheet_html(course, number, generated))

    emit("deadlines.pdf", deadlines_html(courses, generated))
    return PdfReport(written=written)


def _shell(title: str, body: str, generated: str) -> str:
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<title>{esc(title)}</title></head><body>"
        f"{body}</body></html>"
    )


def semester_plan_html(course: dict, generated: str) -> str:
    works = {w["id"]: w for w in course.get("works", [])}
    parts = [f"<h1>{esc(course['code'])} {esc(course.get('title') or '')}</h1>"]

    for session in course.get("sessions", []):
        head = []
        if session.get("week_number"):
            head.append(f"Week {session['week_number']}")
        if session.get("meeting_date"):
            head.append(short_date(session["meeting_date"]))
        if session.get("sub_session_label"):
            head.append(session["sub_session_label"])
        if session.get("topic"):
            head.append(session["topic"])
        parts.append(f"<h2>{esc(' . '.join(str(h) for h in head))}</h2>")

        readings = session.get("readings", [])
        if not readings:
            parts.append(
                f"<p class='entry'>No readings ({esc(session.get('session_type', '').replace('_', ' '))}).</p>"
            )
            continue
        parts.append("<ol>")
        for reading in readings:
            work = works.get(reading.get("work_id"), {})
            extras = []
            if reading.get("requirement_level") and reading["requirement_level"] != "required":
                extras.append(reading["requirement_level"])
            if reading.get("page_range"):
                extras.append(f"pp. {reading['page_range']}")
            if reading.get("access_note"):
                extras.append(reading["access_note"])
            tail = f" [{'; '.join(extras)}]" if extras else ""
            warn = (
                f"<div class='warn'>{esc(reading['content_warning'])}</div>"
                if reading.get("content_warning")
                else ""
            )
            parts.append(
                f"<li class='reading entry'>{esc(citation_line(work))}{esc(tail)}{warn}</li>"
            )
        parts.append("</ol>")

    deliverables = course.get("deliverables", [])
    if deliverables:
        parts.append("<h2>Deadlines</h2><table><thead><tr><th>Due</th><th>Item</th>"
                     "<th>Weight</th><th>Limit</th></tr></thead><tbody>")
        for item in deliverables:
            due = short_date(item.get("due_date")) or item.get("recurrence") or ""
            time = f" {item['due_time'][:5]}" if item.get("due_time") else ""
            limit = f"{item['page_limit']} pages" if item.get("page_limit") else ""
            weight = f"{item['weight_percent']}%" if item.get("weight_percent") else ""
            parts.append(
                f"<tr><td>{esc(due)}{esc(time)}</td><td>{esc(item.get('title'))}</td>"
                f"<td>{esc(weight)}</td><td>{esc(limit)}</td></tr>"
            )
        parts.append("</tbody></table>")

    return _shell(f"{course['code']} semester plan", "".join(parts), generated)


def week_sheet_html(course: dict, number: int, generated: str) -> str:
    works = {w["id"]: w for w in course.get("works", [])}
    sessions = [s for s in course.get("sessions", []) if s.get("week_number") == number]
    parts = [f"<h1>{esc(course['code'])} Week {number}</h1>"]

    for session in sessions:
        head = []
        if session.get("meeting_date"):
            head.append(short_date(session["meeting_date"]))
        if session.get("sub_session_label"):
            head.append(session["sub_session_label"])
        if session.get("topic"):
            head.append(session["topic"])
        parts.append(f"<h2>{esc(' . '.join(str(h) for h in head)) or 'Session'}</h2>")

        readings = session.get("readings", [])
        if not readings:
            parts.append("<p class='entry'>No readings.</p>")
            continue
        parts.append("<ol>")
        for reading in readings:
            work = works.get(reading.get("work_id"), {})
            missing = "" if reading.get("has_document") else " <span class='missing'></span>"
            extras = []
            if reading.get("requirement_level") != "required":
                extras.append(reading.get("requirement_level") or "")
            if reading.get("page_range"):
                extras.append(f"pp. {reading['page_range']}")
            if reading.get("access_note"):
                extras.append(reading["access_note"])
            warn = (
                f"<div class='warn'>{esc(reading['content_warning'])}</div>"
                if reading.get("content_warning")
                else ""
            )
            tail = f" [{'; '.join(e for e in extras if e)}]" if any(extras) else ""
            parts.append(
                f"<li class='reading entry'>{esc(citation_line(work))}{esc(tail)}{missing}{warn}</li>"
            )
        parts.append("</ol>")

    due = [
        item
        for item in course.get("deliverables", [])
        if item.get("recurrence") or item.get("due_date")
    ]
    if due:
        parts.append("<h2>Due</h2><ul>")
        for item in due[:8]:
            when = short_date(item.get("due_date")) or item.get("recurrence") or ""
            time = f" {item['due_time'][:5]}" if item.get("due_time") else ""
            parts.append(f"<li class='entry'>{esc(item.get('title'))}: {esc(when)}{esc(time)}</li>")
        parts.append("</ul>")

    return _shell(f"{course['code']} week {number}", "".join(parts), generated)


def bibliography_html(course: dict, generated: str) -> str:
    works = sorted(
        course.get("works", []),
        key=lambda w: (
            (w.get("authors") or [{}])[0].get("surname")
            or (w.get("authors") or [{}])[0].get("literal")
            or w.get("title")
            or ""
        ).lower(),
    )
    parts = [
        f"<h1>{esc(course['code'])} bibliography</h1>",
        f"<p>Citation style: {esc(course.get('citation_style') or 'default')}.</p>",
        "<ol class='bib'>",
    ]
    for work in works:
        parts.append(f"<li class='entry'>{esc(citation_line(work))}</li>")
    parts.append("</ol>")
    return _shell(f"{course['code']} bibliography", "".join(parts), generated)


def deadlines_html(courses: list[dict], generated: str) -> str:
    dated, recurring, undated = [], [], []
    for course in courses:
        for item in course.get("deliverables", []):
            weight = f"{item['weight_percent']:g}%" if item.get("weight_percent") else ""
            row = (
                item.get("due_date") or "9999-99-99",
                short_date(item.get("due_date")) or item.get("recurrence") or "",
                (item.get("due_time") or "")[:5],
                course["code"],
                item.get("title", ""),
                weight,
            )
            if item.get("due_date"):
                dated.append(row)
            elif item.get("recurrence") == "see schedule":
                dated.append(("9998-99-99",) + row[1:])
            elif item.get("recurrence"):
                recurring.append(row)
            elif weight:
                undated.append(row)
            # a hint with no date and no weight is a session event, not a
            # deadline, and has no business on this document
    dated.sort(key=lambda r: r[0])

    def render_rows(rows: list, head: str) -> list[str]:
        parts = [
            f"<table><thead><tr><th>{head}</th><th>Time</th><th>Course</th>"
            "<th>Item</th><th>Weight</th></tr></thead><tbody>"
        ]
        for _, when, time, code, title, weight in rows:
            parts.append(
                f"<tr><td>{esc(when)}</td><td>{esc(time)}</td><td>{esc(code)}</td>"
                f"<td>{esc(title)}</td><td>{esc(weight)}</td></tr>"
            )
        parts.append("</tbody></table>")
        return parts

    parts = ["<h1>All deadlines</h1>"]
    parts += render_rows(dated, "Due")
    if recurring:
        parts.append("<h2>Recurring</h2>")
        parts += render_rows(recurring, "Repeats")
    if undated:
        parts.append("<h2>No date in the syllabus</h2>")
        parts += render_rows(undated, "")
    return _shell("Deadlines", "".join(parts), generated)
