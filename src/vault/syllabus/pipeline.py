"""run a syllabus pdf through every stage and return a reviewable parse.

nothing here touches the database. the result is a plain structure that can be
written to json, shown for confirmation, edited, and only then committed, which
is what keeps a bad parse from poisoning a whole term.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ..text.model import ExtractedDoc
from . import deliverables as deliv
from . import frontmatter, policies, schedule, zones
from .citations import Citation

DEFAULT_THRESHOLD = 0.75


@dataclass
class ReviewItem:
    entity_type: str
    entity_ref: str
    source_text: str
    confidence: float
    reason: str
    field_name: str | None = None
    guess: dict | None = None


@dataclass
class ParsedSyllabus:
    source_path: str
    source_filename: str
    file_hash: str
    page_count: int
    structure: str
    course: frontmatter.CourseMeta
    policies: list[policies.Policy] = field(default_factory=list)
    sessions: list[schedule.SessionEntry] = field(default_factory=list)
    deliverables: deliv.DeliverableSet = field(default_factory=deliv.DeliverableSet)
    important_dates: list = field(default_factory=list)
    review: list[ReviewItem] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ai_stance(self) -> str:
        return policies.ai_stance_of(self.policies)

    @property
    def reading_count(self) -> int:
        return sum(len(s.readings) for s in self.sessions)

    def to_dict(self) -> dict:
        return {
            "source_path": self.source_path,
            "source_filename": self.source_filename,
            "file_hash": self.file_hash,
            "page_count": self.page_count,
            "structure": self.structure,
            "ai_stance": self.ai_stance,
            "course": _course_dict(self.course),
            "policies": [asdict(p) for p in self.policies],
            "sessions": [_session_dict(s) for s in self.sessions],
            "deliverables": {
                "items": [_deliverable_dict(d) for d in self.deliverables.items],
                "weight_total": self.deliverables.weight_total,
                "weight_warning": self.deliverables.weight_warning,
                "format_notes": self.deliverables.format_notes,
            },
            "important_dates": [
                {
                    "label": d.label,
                    "start": d.start.isoformat() if d.start else None,
                    "end": d.end.isoformat() if d.end else None,
                    "raw": d.raw,
                }
                for d in self.important_dates
            ],
            "review": [asdict(r) for r in self.review],
            "warnings": self.warnings,
        }


def _course_dict(meta: frontmatter.CourseMeta) -> dict:
    return {
        "code": meta.code,
        "title": meta.title,
        "term": meta.term.name if meta.term else None,
        "year": meta.term.year if meta.term else None,
        "instructor_name": meta.instructor_name,
        "instructor_email": meta.instructor_email,
        "meeting_time": meta.meeting_time,
        "location": meta.location,
        "site_url": meta.site_url,
        "citation_style": meta.citation_style,
        "confidence": meta.confidence,
    }


def _citation_dict(citation: Citation) -> dict:
    return {
        "authors": [a.as_dict() for a in citation.authors],
        "title": citation.title,
        "container": citation.container,
        "publisher": citation.publisher,
        "year": citation.year,
        "year_end": citation.year_end,
        "year_is_open": citation.year_is_open,
        "volume": citation.volume,
        "issue": citation.issue,
        "pages": citation.pages,
        "doi": citation.doi,
        "url": citation.url,
        "report_number": citation.report_number,
        "work_type": citation.work_type,
        "matched_pattern": citation.matched_pattern,
        "raw_source_text": citation.raw,
        "signature": citation.signature(),
        "confidence": citation.confidence,
        "suggestion": citation.suggestion.as_dict() if citation.suggestion else None,
    }


def _reading_dict(reading: schedule.ReadingEntry) -> dict:
    return {
        "ordinal": reading.ordinal,
        "requirement_level": reading.requirement_level,
        "page_range": reading.page_range,
        "access_note": reading.access_note,
        "content_warning": reading.content_warning,
        "raw_source_text": reading.raw,
        "confidence": reading.confidence,
        "work": _citation_dict(reading.citation),
    }


def _session_dict(session: schedule.SessionEntry) -> dict:
    return {
        "ordinal": session.ordinal,
        "week_number": session.week_number,
        "meeting_date": session.meeting_date.isoformat() if session.meeting_date else None,
        "sub_session_label": session.sub_session_label,
        "topic": session.topic,
        "section_heading": session.section_heading,
        "session_type": session.session_type,
        "page_number": session.page_number,
        "raw_source_text": session.raw[:600],
        "confidence": session.confidence,
        "readings": [_reading_dict(r) for r in session.readings],
        "deliverable_hints": session.deliverable_hints,
    }


def _deliverable_dict(item: deliv.Deliverable) -> dict:
    return {
        "title": item.title,
        "kind": item.kind,
        "due_date": item.due_date.isoformat() if item.due_date else None,
        "due_time": item.due_time.isoformat() if item.due_time else None,
        "recurrence": item.recurrence,
        "weight_percent": item.weight_percent,
        "page_limit": item.page_limit,
        "word_limit": item.word_limit,
        "format_notes": item.format_notes,
        "requirements_text": item.requirements_text,
        "source_zone": item.source_zone,
        "page_number": item.page_number,
        "confidence": item.confidence,
    }


def parse_syllabus(
    path: str | Path, *, threshold: float = DEFAULT_THRESHOLD, doc: ExtractedDoc | None = None
) -> ParsedSyllabus:
    path = Path(path)
    if doc is None:
        # imported here so the parser itself never needs a pdf library. the
        # browser build hands in an already extracted document instead.
        from ..text.extract import extract_document

        doc = extract_document(path)
    return parse_extracted(doc, threshold=threshold)


def parse_extracted(doc: ExtractedDoc, *, threshold: float = DEFAULT_THRESHOLD) -> ParsedSyllabus:
    path = Path(doc.path)
    zoning = zones.segment(doc)
    meta = frontmatter.parse(doc)
    plan = schedule.parse(doc, zoning, meta.term)

    hints = [
        (hint, session.meeting_date)
        for session in plan.sessions
        for hint in session.deliverable_hints
    ]
    graded = deliv.extract(zoning, meta.term, hints)
    found_policies = policies.extract(zoning)

    parsed = ParsedSyllabus(
        source_path=str(path),
        source_filename=path.name,
        file_hash=doc.file_hash,
        page_count=doc.page_count,
        structure=plan.structure,
        course=meta,
        policies=found_policies,
        sessions=plan.sessions,
        deliverables=graded,
        important_dates=plan.important_dates,
        warnings=list(doc.warnings),
    )

    parsed.review = _collect_review(parsed, threshold)
    parsed.warnings.extend(_sanity_warnings(parsed))
    return parsed


def _collect_review(parsed: ParsedSyllabus, threshold: float) -> list[ReviewItem]:
    items: list[ReviewItem] = []

    if parsed.course.confidence < 1.0:
        missing = [
            name
            for name, value in (
                ("code", parsed.course.code),
                ("title", parsed.course.title),
                ("term", parsed.course.term),
                ("instructor_name", parsed.course.instructor_name),
            )
            if not value
        ]
        if missing:
            items.append(
                ReviewItem(
                    entity_type="course",
                    entity_ref="course",
                    field_name=",".join(missing),
                    source_text=parsed.course.raw[:400],
                    confidence=parsed.course.confidence,
                    reason=f"could not find {', '.join(missing)}",
                    guess=_course_dict(parsed.course),
                )
            )

    for session in parsed.sessions:
        if session.week_number is None and session.meeting_date is None:
            items.append(
                ReviewItem(
                    entity_type="session",
                    entity_ref=f"session[{session.ordinal}]",
                    source_text=session.raw[:300],
                    confidence=0.4,
                    reason="no week number and no date",
                    guess=_session_dict(session),
                )
            )
        for reading in session.readings:
            citation = reading.citation
            if not citation.parsed:
                reason = "no citation pattern matched"
                if citation.suggestion:
                    reason += f", {citation.suggestion.source} suggests a match"
                items.append(
                    ReviewItem(
                        entity_type="work",
                        entity_ref=f"session[{session.ordinal}].reading[{reading.ordinal}]",
                        source_text=reading.raw,
                        confidence=0.0,
                        reason=reason,
                        guess=_citation_dict(citation),
                    )
                )
            elif citation.confidence < threshold:
                items.append(
                    ReviewItem(
                        entity_type="work",
                        entity_ref=f"session[{session.ordinal}].reading[{reading.ordinal}]",
                        source_text=reading.raw,
                        confidence=citation.confidence,
                        reason=f"matched {citation.matched_pattern} but scored low",
                        guess=_citation_dict(citation),
                    )
                )

    for index, item in enumerate(parsed.deliverables.items):
        if item.confidence < threshold:
            items.append(
                ReviewItem(
                    entity_type="deliverable",
                    entity_ref=f"deliverable[{index}]",
                    source_text=item.requirements_text[:400],
                    confidence=item.confidence,
                    reason="incomplete deliverable",
                    guess=_deliverable_dict(item),
                )
            )

    for index, policy in enumerate(parsed.policies):
        if policy.confidence < threshold:
            items.append(
                ReviewItem(
                    entity_type="policy",
                    entity_ref=f"policy[{index}]",
                    source_text=policy.body[:400],
                    confidence=policy.confidence,
                    reason=f"{policy.policy_type} policy not found in the document",
                    guess={"policy_type": policy.policy_type, "ai_stance": policy.ai_stance},
                )
            )

    return items


def _sanity_warnings(parsed: ParsedSyllabus) -> list[str]:
    """checks that catch a parse which looks fine but is not.

    a silently dropped week or a duplicated date is invisible unless something
    counts, so these run on every parse and are shown during review.

    they are written for whoever is looking at the review page, which is a
    student with their syllabus open, not the person who wrote the parser.
    each one says what was found and where to look, and none of them use a
    word like session or zone that only means something inside this code.
    """
    notes: list[str] = []

    if parsed.deliverables.weight_warning:
        notes.append(parsed.deliverables.weight_warning)

    if not parsed.sessions:
        notes.append(
            "No weekly schedule was found in this PDF. That usually means it "
            "is not in the file, and lives on the course site instead. The "
            "course details and grading below still came through."
        )

    # a gap in the week numbers is worth reporting, but only when the numbers
    # really are weeks. a syllabus that numbers every meeting runs past twenty,
    # and a break in that sequence is a cancelled class, not a missing parse.
    weeks = [s.week_number for s in parsed.sessions if s.week_number]
    if weeks and max(weeks) <= 17:
        missing = sorted(set(range(min(weeks), max(weeks) + 1)) - set(weeks))
        if missing:
            notes.append(
                f"{_weeks_phrase(missing)} {'is' if len(missing) == 1 else 'are'}"
                " missing from the schedule. That is often a reading week or a "
                "break, but it is worth a look."
            )

    dated = [s for s in parsed.sessions if s.meeting_date]
    seen: dict[dt.date, int] = {}
    for session in dated:
        key = (session.meeting_date, session.sub_session_label)
        if key in seen:
            notes.append(
                f"Weeks {seen[key]} and {session.week_number} are both dated "
                f"{session.meeting_date.strftime('%d %B')}. One of them is "
                "probably wrong."
            )
        seen[key] = session.week_number or 0

    empty = [s.week_number for s in parsed.sessions
             if s.session_type == "reading" and not s.readings and s.week_number]
    if empty:
        notes.append(
            f"{_weeks_phrase(empty)} {'has' if len(empty) == 1 else 'have'} no "
            "readings listed. Often that is a break or an exam week."
        )

    return notes


def _weeks_phrase(weeks: list[int]) -> str:
    """"Week 4" or "Weeks 4, 9 and 10", so a sentence can be built on it."""
    numbers = [str(w) for w in weeks]
    if len(numbers) == 1:
        return f"Week {numbers[0]}"
    return "Weeks " + ", ".join(numbers[:-1]) + f" and {numbers[-1]}"
