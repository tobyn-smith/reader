"""html for the built site.

plain strings rather than a template engine. the whole output is a handful of
tables and a stylesheet, and a dependency would be larger than the thing it
renders.
"""

from __future__ import annotations

import datetime as dt
import html
import re

STYLESHEET = "site.css"


def esc(value) -> str:
    return html.escape(str(value)) if value is not None else ""


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-") or "untitled"


def page(title: str, body: str, *, depth: int = 0, nav: str = "", search: bool = False) -> str:
    up = "../" * depth
    scripts = ""
    if search:
        scripts = (
            f'<link href="{up}pagefind/pagefind-ui.css" rel="stylesheet">'
            f'<script src="{up}pagefind/pagefind-ui.js"></script>'
        )
    return (
        "<!doctype html>\n"
        '<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{esc(title)}</title>\n"
        f'<link rel="stylesheet" href="{up}{STYLESHEET}">\n'
        f"{scripts}\n</head>\n<body>\n"
        f"{nav}\n<main>\n{body}\n</main>\n</body>\n</html>\n"
    )


def nav(courses: list[dict], depth: int = 0, private: bool = False) -> str:
    up = "../" * depth
    links = [f'<a href="{up}index.html">All</a>']
    for course in courses:
        target = f"{up}course/{slug(course['code'])}/index.html"
        links.append(f'<a href="{target}">{esc(course["code"])}</a>')
    links.append(f'<a href="{up}deadlines.html">Deadlines</a>')
    links.append(f'<a href="{up}search.html">Search</a>')
    tag = ' <span class="private">private build</span>' if private else ""
    return f'<nav>{" ".join(links)}{tag}</nav>'


def authors_label(authors: list[dict]) -> str:
    names = []
    for author in authors:
        if author.get("literal"):
            names.append(author["literal"])
        else:
            surname = author.get("surname", "")
            given = author.get("given", "")
            names.append(f"{surname}, {given}".strip().strip(","))
    if not names:
        return ""
    if len(names) > 3:
        return f"{names[0]} et al."
    return "; ".join(names)


def citation_line(work: dict) -> str:
    if work.get("rendered_citation"):
        return work["rendered_citation"]

    bits = []
    authors = authors_label(work.get("authors", []))
    if authors:
        bits.append(authors)
    year = work.get("year")
    if year:
        label = str(year)
        if work.get("year_is_open"):
            label += "-"
        elif work.get("year_end"):
            label += f"-{work['year_end']}"
        bits.append(label)
    if work.get("title"):
        bits.append(f"“{work['title']}.”")
    if work.get("container"):
        bits.append(work["container"])
    volume = work.get("volume")
    if volume:
        issue = work.get("issue")
        bits.append(f"{volume}({issue})" if issue else str(volume))
    if work.get("pages"):
        bits.append(str(work["pages"]))
    if work.get("report_number"):
        bits.append(work["report_number"])
    return ". ".join(str(b) for b in bits if b)


def short_date(value: str | None) -> str:
    if not value:
        return ""
    try:
        parsed = dt.date.fromisoformat(value)
    except ValueError:
        return esc(value)
    return f"{parsed.month}/{parsed.day}"


def table(headers: list[str], rows: list[list[str]], *, css: str = "") -> str:
    if not rows:
        return '<p class="empty">None.</p>'
    head = "".join(f"<th>{esc(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>" for row in rows)
    attr = f' class="{css}"' if css else ""
    return f"<table{attr}><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def stance_note(stance: str | None) -> str:
    if not stance or stance == "unstated":
        return '<p class="policy">AI use policy: not stated in the syllabus.</p>'
    css = "flag" if stance in {"prohibited", "restricted"} else "policy"
    extra = " Brief generation is disabled for this course." if stance in {"prohibited", "restricted"} else ""
    return f'<p class="{css}">AI use policy: {esc(stance)}.{extra}</p>'
