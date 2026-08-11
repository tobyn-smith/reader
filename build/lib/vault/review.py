"""the confirmation step between parsing and the database.

a syllabus is parsed once a term and a wrong parse poisons everything downstream,
so nothing is written until the parse has been looked at. the review walks the
low confidence rows one at a time, showing the extracted fields beside the exact
source text they came from.
"""

from __future__ import annotations

import json
import sys

from .syllabus.pipeline import ParsedSyllabus


def review_and_confirm(parsed: ParsedSyllabus, *, auto_accept: bool = False) -> dict | None:
    data = parsed.to_dict()
    _print_summary(parsed)

    if auto_accept:
        for item in data["review"]:
            item["decision"] = "accepted"
        return data

    if not sys.stdin.isatty():
        print(
            "stdin is not a terminal, so the review prompt cannot run.\n"
            "use --yes to accept as parsed, or --json to write the parse to a file.",
            file=sys.stderr,
        )
        return None

    for item in data["review"]:
        decision = _review_one(item)
        if decision == "quit":
            return None
        item["decision"] = decision

    print()
    answer = input("write this parse to the database? [y/n] ").strip().lower()
    if answer not in {"y", "yes"}:
        return None

    _apply_rejections(data)
    return data


def _print_summary(parsed: ParsedSyllabus) -> None:
    course = parsed.course
    term = str(course.term) if course.term else "term unknown"
    print()
    print(f"{course.code or 'code?'}  {course.title or 'title?'}  ({term})")
    print(f"structure: {parsed.structure}, ai policy: {parsed.ai_stance}")
    print(f"{len(parsed.sessions)} sessions, {parsed.reading_count} readings, "
          f"{len(parsed.deliverables.items)} deliverables, {len(parsed.policies)} policies")

    for session in parsed.sessions:
        date = session.meeting_date.isoformat() if session.meeting_date else "no date"
        week = f"week {session.week_number}" if session.week_number else "     "
        sub = f" {session.sub_session_label}" if session.sub_session_label else ""
        count = f"{len(session.readings)} readings" if session.readings else session.session_type
        print(f"  {week:8s} {date}{sub}  {count:14s} {(session.topic or '')[:46]}")

    for warning in parsed.warnings:
        print(f"  check: {warning}")

    if parsed.review:
        print(f"\n{len(parsed.review)} rows scored below the confidence threshold.")


def _review_one(item: dict) -> str:
    print()
    print(f"[{item['entity_type']}] {item['reason']} (confidence {item['confidence']})")
    print(f"  source: {item['source_text'][:300]}")
    guess = item.get("guess") or {}
    shown = {k: v for k, v in guess.items() if v not in (None, [], "", {})}
    for key in ("raw_source_text", "signature", "confidence", "matched_pattern"):
        shown.pop(key, None)
    if shown:
        print(f"  parsed: {json.dumps(shown, ensure_ascii=False, default=str)[:300]}")

    while True:
        answer = input("  [a]ccept  [e]dit  [r]eject  [q]uit: ").strip().lower()
        if answer in {"a", ""}:
            return "accepted"
        if answer == "r":
            return "rejected"
        if answer == "q":
            return "quit"
        if answer == "e":
            edited = _edit(guess)
            if edited is not None:
                item["decided_value"] = edited
                return "edited"


def _edit(guess: dict) -> dict | None:
    print("  enter field=value pairs, one per line, blank line to finish")
    updates: dict = {}
    while True:
        line = input("    ").strip()
        if not line:
            break
        key, sep, value = line.partition("=")
        if not sep:
            print("    expected field=value")
            continue
        updates[key.strip()] = value.strip() or None
    if not updates:
        return None
    merged = dict(guess)
    merged.update(updates)
    return merged


def _apply_rejections(data: dict) -> None:
    """remove rows the review rejected and fold in edits before the write."""
    rejected_refs = {
        item["entity_ref"] for item in data["review"] if item["decision"] == "rejected"
    }
    edited = {
        item["entity_ref"]: item["decided_value"]
        for item in data["review"]
        if item["decision"] == "edited" and item.get("decided_value")
    }

    for session in data["sessions"]:
        ref = f"session[{session['ordinal']}]"
        session["readings"] = [
            r for r in session["readings"]
            if f"{ref}.reading[{r['ordinal']}]" not in rejected_refs
        ]
        for reading in session["readings"]:
            reading_ref = f"{ref}.reading[{reading['ordinal']}]"
            if reading_ref in edited:
                reading["work"].update(edited[reading_ref])

    if "course" in edited or "course" in {r for r in edited}:
        pass
    for ref, value in edited.items():
        if ref == "course":
            data["course"].update(value)

    data["deliverables"]["items"] = [
        item
        for index, item in enumerate(data["deliverables"]["items"])
        if f"deliverable[{index}]" not in rejected_refs
    ]
