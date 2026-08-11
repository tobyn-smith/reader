"""tell a syllabus from a reading.

the two are not ambiguous in practice. a syllabus names weeks, states what
things are worth, and lists an instructor. a journal article has an abstract,
a reference list, and a doi. asking someone to sort their own pile of pdfs
first is asking them to do the tool's job.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .text.model import ExtractedDoc

SYLLABUS = "syllabus"
READING = "reading"

_WEEK = re.compile(r"\b(?:week|session|class|unit|module)\s*#?\s*\d{1,2}\b", re.IGNORECASE)
_WEIGHT = re.compile(r"\b\d{1,3}\s?%|\b\d{1,3}\s+percent\b", re.IGNORECASE)
_COURSE_WORDS = re.compile(
    r"\b(syllabus|office hours|instructor|grading scale|course description|"
    r"required readings|attendance policy|academic honesty|late work|"
    r"course objectives|prerequisite)\b",
    re.IGNORECASE,
)
_READING_WORDS = re.compile(
    r"\b(abstract|keywords|works cited|bibliography|references|"
    r"acknowledgements|received\s+\d|accepted\s+\d)\b",
    re.IGNORECASE,
)
_DOI = re.compile(r"\b10\.\d{4,9}/\S+", re.IGNORECASE)
_SYLLABUS_WORD = re.compile(r"\bsyllabus\b", re.IGNORECASE)
_SCHEDULE_DATE = re.compile(r"\b\d{1,2}\s*/\s*\d{1,2}\b")
# a letter grade next to a number range, in any of the usual arrangements
_GRADING_SCALE = re.compile(
    r"\b[A-D][+-]?\s*[:=]\s*\d{2,3}|\b\d{2,3}(?:\.\d+)?\s*(?:to|[-–])\s*\d{2,3}(?:\.\d+)?\s*[:=]?\s*[A-D][+-]?\b"
    r"|\b[A-D][+-]?\s*(?:≥|>=)\s*\d{2,3}",
    re.IGNORECASE,
)


@dataclass
class Classification:
    kind: str
    confidence: float
    reasons: list[str] = field(default_factory=list)


def classify(doc: ExtractedDoc) -> Classification:
    from .syllabus.frontmatter import parse as parse_frontmatter

    text = "\n".join(page.text for page in doc.pages[:6])
    head = "\n".join(page.text for page in doc.pages[:2])

    weeks = len(set(_WEEK.findall(text)))
    dates = len(_SCHEDULE_DATE.findall(text))
    weights = len(_WEIGHT.findall(text))
    course_words = len(set(w.lower() for w in _COURSE_WORDS.findall(text)))
    reading_words = len(set(w.lower() for w in _READING_WORDS.findall(text)))

    score = 0.0
    reasons: list[str] = []

    # a course code together with a term is the most reliable signal there is.
    # plenty of syllabi number nothing and schedule everything by date, so this
    # has to carry weight on its own.
    meta = parse_frontmatter(doc)
    if meta.code and meta.term:
        score += 0.35
        reasons.append(f"{meta.code} {meta.term}")

    # a run of week markers is strong. one stray "week 3" in an article is not.
    if weeks >= 3:
        score += 0.4
        reasons.append(f"{weeks} week markers")
    elif weeks >= 1:
        score += 0.1

    if dates >= 5:
        score += 0.25
        reasons.append("dated schedule")

    if weights >= 2:
        score += 0.15
        reasons.append("stated weights")
    if course_words >= 2:
        score += 0.2
        reasons.append("course front matter")
    if _GRADING_SCALE.search(text):
        score += 0.2
        reasons.append("grading scale")
    if _SYLLABUS_WORD.search(head):
        score += 0.2
        reasons.append("calls itself a syllabus")

    if _DOI.search(head):
        score -= 0.3
        reasons.append("has a doi")
    if reading_words >= 2:
        score -= 0.15
        reasons.append("article sections")

    kind = SYLLABUS if score >= 0.5 else READING
    return Classification(kind, round(min(1.0, abs(score - 0.5) * 2), 3), reasons)
