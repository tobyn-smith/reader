"""course identity from the first page or two."""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..text.model import ExtractedDoc
from ..text.normalize import URL_RE, collapse_whitespace
from .dates import Term, find_term

# a course code is letters then digits, usually with a space between
CODE_RE = re.compile(r"\b([A-Z]{2,5})\s*[- ]?\s*(\d{3,5}[A-Z]?)\b")
EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")

_LABELLED = {
    "instructor": re.compile(
        r"^\s*(?:instructor|professor|taught by|lecturer)\s*:?\s*(?P<value>.+)$", re.IGNORECASE
    ),
    "email": re.compile(r"^\s*e-?mail\s*:?\s*(?P<value>.+)$", re.IGNORECASE),
    "time": re.compile(
        r"^\s*(?:time|class time|meeting time|meets|meeting times?(?: and location)?)\s*:?\s*(?P<value>.+)$",
        re.IGNORECASE,
    ),
    "location": re.compile(
        r"^\s*(?:place|location|room|classroom)\s*:?\s*(?P<value>.+)$", re.IGNORECASE
    ),
    "site": re.compile(
        r"^\s*(?:course (?:website|site|page|pages)|website)\s*:?\s*(?P<value>.+)$", re.IGNORECASE
    ),
}

# style guides a syllabus may require, overriding the personal default
_STYLE_RE = re.compile(
    r"\b(apsr|apa|mla|chicago|turabian|harvard|ieee|ama|bluebook|asa)\b", re.IGNORECASE
)


@dataclass
class CourseMeta:
    code: str | None = None
    title: str | None = None
    term: Term | None = None
    instructor_name: str | None = None
    instructor_email: str | None = None
    meeting_time: str | None = None
    location: str | None = None
    site_url: str | None = None
    citation_style: str | None = None
    confidence: float = 0.0
    raw: str = ""


def find_term_in_document(doc: ExtractedDoc) -> Term | None:
    """look in the untouched page text.

    the term is very often printed in the running header, which header stripping
    removes on purpose, so the cleaned text is the wrong place to look for it.
    """
    for page in doc.pages[:3]:
        found = find_term(page.raw_text) or find_term(page.text)
        if found:
            return found
    return find_term(doc.text)


def parse(doc: ExtractedDoc) -> CourseMeta:
    head = "\n".join(page.raw_text for page in doc.pages[:2])
    meta = CourseMeta(raw=head)
    lines = [collapse_whitespace(line) for line in head.splitlines()]
    lines = [line for line in lines if line]

    meta.term = find_term_in_document(doc)

    code = CODE_RE.search(head)
    if code:
        meta.code = f"{code.group(1)} {code.group(2)}"

    meta.title = _find_title(lines, meta.code)

    values = _labelled_values(lines)
    meta.instructor_name = values.get("instructor")
    meta.meeting_time = values.get("time")
    meta.location = values.get("location")

    email = EMAIL_RE.search(head)
    if email:
        meta.instructor_email = email.group(0)
    if meta.instructor_name:
        meta.instructor_name = EMAIL_RE.sub("", meta.instructor_name).strip(" ,;")

    site = values.get("site") or ""
    url = URL_RE.search(site) or URL_RE.search(head)
    if url:
        meta.site_url = url.group(0).rstrip(".,;)")

    style = _STYLE_RE.search(head)
    if style:
        meta.citation_style = style.group(1).lower()

    meta.confidence = _score(meta)
    return meta


def _labelled_values(lines: list[str]) -> dict[str, str]:
    """read "label: value" pairs, including the two column layouts.

    some syllabi set the labels in one column and the values in another, which
    extracts as a label on its own line followed by its value on the next. an
    empty value therefore falls through to the following line.
    """
    found: dict[str, str] = {}
    for index, line in enumerate(lines):
        for key, pattern in _LABELLED.items():
            if key in found:
                continue
            m = pattern.match(line)
            if not m:
                continue
            value = m.group("value").strip(" :-")
            if not value and index + 1 < len(lines):
                value = lines[index + 1].strip(" :-")
            if value:
                found[key] = value
    return found


_CONTINUES = re.compile(r"(?:\b(?:to|of|and|in|on|for|the|a|an)|[:,&-])$", re.IGNORECASE)


def _find_title(lines: list[str], code: str | None) -> str | None:
    """the most title-like line near the code, joined across wraps.

    a long title wraps in the header block, and each fragment alone looks
    incomplete, so a line that ends mid phrase pulls the following line in.
    """
    if code:
        bare = code.replace(" ", "")
        for index, line in enumerate(lines):
            if bare in line.replace(" ", ""):
                same_line = re.sub(re.escape(code), "", line, flags=re.IGNORECASE)
                same_line = same_line.strip(" :-–—")
                if len(same_line) > 6 and not _is_label(same_line):
                    return _join_wrapped(same_line, lines[index + 1:])
                for offset, candidate in enumerate(lines[index + 1: index + 4]):
                    if len(candidate) > 6 and not _is_label(candidate):
                        return _join_wrapped(
                            candidate.strip(" :-–—"), lines[index + offset + 2:]
                        )
    for line in lines[:6]:
        if len(line) > 10 and not _is_label(line) and not CODE_RE.search(line):
            return line
    return None


def _join_wrapped(title: str, rest: list[str]) -> str:
    for line in rest:
        if len(title) > 90 or not _CONTINUES.search(title):
            break
        candidate = line.strip(" :-–—")
        if not candidate or _is_label(candidate):
            break
        title = f"{title} {candidate}"
    return title.strip()


def _is_label(line: str) -> bool:
    if any(pattern.match(line) for pattern in _LABELLED.values()):
        return True
    return bool(EMAIL_RE.search(line) or URL_RE.search(line)) or find_term(line) is not None


def _score(meta: CourseMeta) -> float:
    have = [meta.code, meta.title, meta.term, meta.instructor_name]
    return round(sum(1 for value in have if value) / len(have), 3)
